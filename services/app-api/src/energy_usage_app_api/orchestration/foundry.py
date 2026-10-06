"""Runs one chat turn against the Foundry prompt agent. The agent only *requests* tools; this process
executes them with the user's OBO token (identity option B), so Foundry never sees user tokens."""

import json
import logging
import os
from typing import Any

from opentelemetry import trace

from energy_usage_shared.contracts import AgentOutput

from ..application.errors import AgentLoopLimit, UpstreamUnavailable
from ..application.models import AgentTurn, Emit, ToolCall
from ..application.ports import ToolGateway

_log = logging.getLogger("energy_usage.agent")
_tracer = trace.get_tracer("energy_usage.agent")
MAX_ROWS_TO_MODEL = 100
CONTENT_FILTER_ANSWER = "I can only help with questions about your own energy usage."


def instrument_genai() -> None:
    """GenAI spans for Responses/Conversations calls (shown in App Insights and Foundry Tracing).
    Opt-in via AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true; content capture via
    OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT."""
    if os.environ.get("AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING", "").lower() != "true":
        return
    try:
        from azure.ai.projects.telemetry import AIProjectInstrumentor

        AIProjectInstrumentor().instrument()
        _guard_non_recording_spans()
    except Exception:  # tracing must never break chat
        _log.warning("genai_instrumentation_failed", exc_info=True)


def _guard_non_recording_spans() -> None:
    """azure-ai-projects 2.8 (preview tracing) reads `span.attributes` on non-recording spans, which
    raises after the model call succeeded and loses the answer. Skip message capture for those spans.
    Remove when the SDK checks `is_recording()` itself."""
    from azure.ai.projects.telemetry import _responses_instrumentor as ri

    cls = ri._ResponsesInstrumentorPreview
    original = cls._append_to_message_attribute
    if getattr(original, "_energy_usage_guarded", False):
        return

    def guarded(self: Any, span: Any, attribute_name: str, new_messages: Any) -> None:
        if span is not None and span.span_instance.is_recording():
            original(self, span, attribute_name, new_messages)

    guarded._energy_usage_guarded = True  # type: ignore[attr-defined]
    cls._append_to_message_attribute = guarded


def is_content_filtered(exc: BaseException) -> bool:
    """Azure OpenAI blocked the prompt (e.g. a jailbreak attempt): answer as a refusal, not an outage."""
    return getattr(exc, "code", None) == "content_filter"


def tool_output_for_model(call: ToolCall) -> str:
    """Compact JSON for the model. The full result stays in-process for projections."""
    if call.error:
        return json.dumps({"error": call.error.model_dump()})
    r = call.result
    assert r is not None
    rows = r.rows[:MAX_ROWS_TO_MODEL]
    body: dict[str, Any] = {
        "result_id": r.result_id,
        "unit": r.unit,
        "tz": r.tz,
        "columns": [c.key for c in r.columns],
        "rows": rows,
        "summary": r.summary,
        "assumptions": r.assumptions,
    }
    if len(r.rows) > len(rows):
        body["rows_truncated"] = f"showing {len(rows)} of {len(r.rows)} rows; the user sees all of them"
    return json.dumps(body, default=str)


def parse_output(text: str) -> AgentOutput:
    try:
        return AgentOutput.model_validate_json(text)
    except ValueError:
        _log.warning("agent_output_not_json", extra={"event": "agent_output_not_json"})
        return AgentOutput(answer=text.strip() or "Sorry, I couldn't produce an answer.", status="ok")


class FoundryAgentRunner:
    def __init__(self, openai: Any, agent_name: str, max_rounds: int, closers: tuple[Any, ...] = ()) -> None:
        self._openai = openai
        self._agent_ref = {"agent_reference": {"name": agent_name, "type": "agent_reference"}}
        self._max_rounds = max_rounds
        self._closers = closers

    @classmethod
    def connect(
        cls, endpoint: str, agent_name: str, max_rounds: int, client_id: str | None = None
    ) -> "FoundryAgentRunner":
        from azure.ai.projects.aio import AIProjectClient
        from azure.identity.aio import DefaultAzureCredential

        instrument_genai()
        credential = DefaultAzureCredential(managed_identity_client_id=client_id)
        project = AIProjectClient(endpoint=endpoint, credential=credential)
        return cls(project.get_openai_client(), agent_name, max_rounds, closers=(project, credential))

    async def run_turn(
        self, message: str, agent_conversation_id: str | None, tools: ToolGateway, emit: Emit
    ) -> AgentTurn:
        name = self._agent_ref["agent_reference"]["name"]
        with _tracer.start_as_current_span(f"invoke_agent {name}") as span:
            span.set_attribute("gen_ai.operation.name", "invoke_agent")
            span.set_attribute("gen_ai.agent.name", name)
            turn = await self._run_turn(message, agent_conversation_id, tools, emit)
            span.set_attribute("gen_ai.conversation.id", turn.agent_conversation_id or "")
            span.set_attribute("energy_usage.tool_calls", len(turn.calls))
            return turn

    async def _run_turn(
        self, message: str, agent_conversation_id: str | None, tools: ToolGateway, emit: Emit
    ) -> AgentTurn:
        try:
            if agent_conversation_id is None:
                agent_conversation_id = (await self._openai.conversations.create()).id
            response = await self._openai.responses.create(
                conversation=agent_conversation_id, input=message, extra_body=self._agent_ref
            )
        except UpstreamUnavailable:
            raise
        except Exception as exc:
            if is_content_filtered(exc) and agent_conversation_id:
                _log.warning("agent_content_filtered", extra={"event": "agent_content_filtered"})
                return AgentTurn(
                    AgentOutput(answer=CONTENT_FILTER_ANSWER, status="refused"), agent_conversation_id, []
                )
            _log.exception("agent_call_failed")
            raise UpstreamUnavailable("The assistant is unavailable.") from exc

        calls: list[ToolCall] = []
        for _ in range(self._max_rounds):
            requested = [o for o in response.output if getattr(o, "type", None) == "function_call"]
            if not requested:
                return AgentTurn(parse_output(response.output_text), agent_conversation_id, calls)
            outputs = []
            for fc in requested:
                await emit("status", {"stage": "tool", "tool": fc.name})
                try:
                    args = json.loads(fc.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                with _tracer.start_as_current_span(f"execute_tool {fc.name}") as span:
                    span.set_attribute("gen_ai.operation.name", "execute_tool")
                    span.set_attribute("gen_ai.tool.name", fc.name)
                    span.set_attribute("gen_ai.tool.call.id", fc.call_id)
                    call = await tools.call(fc.name, args)
                    span.set_attribute("energy_usage.tool.rows", len(call.result.rows) if call.result else 0)
                    if call.error:
                        span.set_attribute("error.type", call.error.code)
                calls.append(call)
                outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": fc.call_id,
                        "output": tool_output_for_model(call),
                    }
                )
            try:
                response = await self._openai.responses.create(
                    conversation=agent_conversation_id, input=outputs, extra_body=self._agent_ref
                )
            except Exception as exc:
                if is_content_filtered(exc):
                    _log.warning("agent_content_filtered", extra={"event": "agent_content_filtered"})
                    output = AgentOutput(answer=CONTENT_FILTER_ANSWER, status="refused")
                    return AgentTurn(output, agent_conversation_id, calls)
                _log.exception("agent_call_failed")
                raise UpstreamUnavailable("The assistant is unavailable.") from exc
        raise AgentLoopLimit(agent_conversation_id)

    async def forget(self, agent_conversation_id: str) -> None:
        await self._openai.conversations.delete(agent_conversation_id)

    async def aclose(self) -> None:
        await self._openai.close()
        for c in self._closers:
            await c.close()
