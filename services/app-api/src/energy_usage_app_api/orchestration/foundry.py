"""Runs one chat turn against the Foundry prompt agent. The agent only *requests* tools; this process
executes them with the user's OBO token (identity option B), so Foundry never sees user tokens."""

import asyncio
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
# Reasoning turns can take a while; anything longer is treated as an outage.
FOUNDRY_TIMEOUT_SECONDS = 120.0
FOUNDRY_CONNECT_TIMEOUT_SECONDS = 10.0
FOUNDRY_MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 1.0
CLOSE_TIMEOUT_SECONDS = 5.0
ABORTED_OUTPUT = json.dumps(
    {
        "error": {
            "code": "aborted",
            "message": "This tool call was interrupted and did not run. Do not retry it.",
        }
    }
)


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


def is_pending_tool_output(exc: BaseException) -> bool:
    """Foundry rejects input while the conversation has a function_call without output:
    400 invalid_request_error "No tool output found for function call call_..."."""
    if getattr(exc, "status_code", None) != 400:
        return False
    body = getattr(exc, "body", None)
    text = f"{body.get('message', '') if isinstance(body, dict) else ''} {exc}".lower()
    return "tool output" in text and "function call" in text


def _never_processed(exc: BaseException) -> bool:
    """Safe to resend: throttled (429) or the connection was never established."""
    if getattr(exc, "status_code", None) == 429:
        return True
    cause: BaseException | None = exc
    while cause is not None:
        if type(cause).__name__ == "ConnectError":
            return True
        cause = cause.__cause__
    return False


def _unavailable(exc: BaseException) -> UpstreamUnavailable:
    _log.warning(
        "agent_call_failed",
        extra={
            "event": "agent_call_failed",
            "error": type(exc).__name__,
            "status_code": getattr(exc, "status_code", None),
            "request_id": getattr(exc, "request_id", None),
        },
    )
    return UpstreamUnavailable("The assistant is unavailable. Try again in a moment.")


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
        # Model calls are not idempotent (a timed-out request may already have been applied), so the SDK
        # must not retry them; `_create_response` retries only failures that were never processed.
        self._responses = openai.with_options(max_retries=0).responses
        self._agent_ref = {"agent_reference": {"name": agent_name, "type": "agent_reference"}}
        self._max_rounds = max_rounds
        self._closers = closers
        self._background: set[asyncio.Task[None]] = set()

    @classmethod
    def connect(
        cls, endpoint: str, agent_name: str, max_rounds: int, client_id: str | None = None
    ) -> "FoundryAgentRunner":
        from azure.ai.projects.aio import AIProjectClient
        from azure.identity.aio import DefaultAzureCredential
        from openai import Timeout

        instrument_genai()
        credential = DefaultAzureCredential(managed_identity_client_id=client_id)
        project = AIProjectClient(endpoint=endpoint, credential=credential)
        openai = project.get_openai_client(
            timeout=Timeout(FOUNDRY_TIMEOUT_SECONDS, connect=FOUNDRY_CONNECT_TIMEOUT_SECONDS),
            max_retries=FOUNDRY_MAX_RETRIES,
        )
        return cls(openai, agent_name, max_rounds, closers=(project, credential))

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
                agent_conversation_id = await self._new_conversation()
            try:
                response = await self._create_response(agent_conversation_id, message)
            except Exception as exc:
                if not is_pending_tool_output(exc):
                    raise
                # An earlier turn ended with unanswered tool calls (e.g. the process died mid-turn), so
                # Foundry rejects every new message. Continue in a fresh conversation instead of failing.
                _log.warning(
                    "agent_conversation_reset",
                    extra={"event": "agent_conversation_reset", "reason": "pending_tool_output"},
                )
                agent_conversation_id = await self._new_conversation()
                response = await self._create_response(agent_conversation_id, message)
        except UpstreamUnavailable:
            raise
        except Exception as exc:
            if is_content_filtered(exc) and agent_conversation_id:
                _log.warning("agent_content_filtered", extra={"event": "agent_content_filtered"})
                return AgentTurn(
                    AgentOutput(answer=CONTENT_FILTER_ANSWER, status="refused"), agent_conversation_id, []
                )
            raise _unavailable(exc) from exc

        calls: list[ToolCall] = []
        pending: list[str] = []  # call ids Foundry is waiting on; closed if the turn ends early
        try:
            rounds = 0
            while True:
                requested = [o for o in response.output if getattr(o, "type", None) == "function_call"]
                if not requested:
                    return AgentTurn(parse_output(response.output_text), agent_conversation_id, calls)
                pending = [fc.call_id for fc in requested]
                if rounds == self._max_rounds:
                    raise AgentLoopLimit(agent_conversation_id)
                rounds += 1
                outputs = []
                for fc in requested:
                    call = await self._execute(fc, tools, emit)
                    calls.append(call)
                    outputs.append(
                        {
                            "type": "function_call_output",
                            "call_id": fc.call_id,
                            "output": tool_output_for_model(call),
                        }
                    )
                try:
                    response = await self._create_response(agent_conversation_id, outputs)
                except Exception as exc:
                    if is_content_filtered(exc):
                        _log.warning("agent_content_filtered", extra={"event": "agent_content_filtered"})
                        await self._close_pending(agent_conversation_id, pending, "content_filtered")
                        output = AgentOutput(answer=CONTENT_FILTER_ANSWER, status="refused")
                        return AgentTurn(output, agent_conversation_id, calls)
                    raise _unavailable(exc) from exc
                pending = []
        except BaseException as exc:
            await self._close_pending(agent_conversation_id, pending, type(exc).__name__)
            raise

    async def _execute(self, fc: Any, tools: ToolGateway, emit: Emit) -> ToolCall:
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
        return call

    async def _new_conversation(self) -> str:
        return str((await self._openai.conversations.create()).id)

    async def _create_response(self, conversation: str, input: Any) -> Any:
        for attempt in range(FOUNDRY_MAX_RETRIES + 1):
            try:
                return await self._responses.create(
                    conversation=conversation, input=input, extra_body=self._agent_ref
                )
            except Exception as exc:
                if attempt == FOUNDRY_MAX_RETRIES or not _never_processed(exc):
                    raise
                _log.warning(
                    "agent_call_retry",
                    extra={"event": "agent_call_retry", "attempt": attempt + 1, "error": type(exc).__name__},
                )
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
        raise AssertionError("unreachable")

    async def _close_pending(self, conversation: str, call_ids: list[str], reason: str) -> None:
        """Answer unanswered tool calls so the conversation stays usable. Adding items does not run the
        model (sending outputs through `responses.create` makes it request the tool again). Best effort:
        bounded, shielded from cancellation (it finishes in the background) and never raises."""
        if not call_ids:
            return
        task = asyncio.create_task(self._submit_aborted(conversation, list(call_ids), reason))
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            pass  # the caller re-raises the original exception; the task completes on its own

    async def _submit_aborted(self, conversation: str, call_ids: list[str], reason: str) -> None:
        items = [{"type": "function_call_output", "call_id": c, "output": ABORTED_OUTPUT} for c in call_ids]
        try:
            await asyncio.wait_for(
                self._openai.conversations.items.create(conversation, items=items), CLOSE_TIMEOUT_SECONDS
            )
            _log.info(
                "agent_tool_calls_closed",
                extra={"event": "agent_tool_calls_closed", "count": len(call_ids), "reason": reason},
            )
        except Exception as exc:
            _log.warning(
                "agent_tool_calls_close_failed",
                extra={
                    "event": "agent_tool_calls_close_failed",
                    "count": len(call_ids),
                    "reason": reason,
                    "error": type(exc).__name__,
                },
            )

    async def forget(self, agent_conversation_id: str) -> None:
        await self._openai.conversations.delete(agent_conversation_id)

    async def aclose(self) -> None:
        await self._openai.close()
        for c in self._closers:
            await c.close()
