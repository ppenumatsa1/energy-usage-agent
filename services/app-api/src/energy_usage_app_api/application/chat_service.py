"""The chat use case (BR-1, BR-2, BR-6, BR-11, BR-12). Numbers in the table/chart come from projections."""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from energy_usage_shared.auth import Principal

from ..projections import View, project
from .errors import AgentLoopLimit, ConversationNotFound, NotOnboarded, RateLimited
from .models import (
    ChartData,
    ChatRequest,
    ChatResponse,
    ChatStatus,
    ConversationDetail,
    ConversationRecord,
    ConversationSummary,
    ConversationTurn,
    Emit,
    MeResponse,
    StatusComponent,
    StatusResponse,
    StoredTurn,
    TableData,
    ToolCall,
    no_emit,
)
from .ports import AgentRunner, ConversationStore, OboProvider, ProfileClient, RateLimiter, ToolGatewayFactory
from .trace import TimedGateway, build_trace

_log = logging.getLogger("energy_usage.chat")
LOOP_LIMIT_ANSWER = (
    "I couldn't finish answering that. Try asking in a simpler way, for example one period at a time."
)


@dataclass(frozen=True)
class PreparedChat:
    principal: Principal
    message: str
    user_token: str
    conversation: ConversationRecord | None
    correlation_id: str


class ChatService:
    def __init__(
        self,
        *,
        agent: AgentRunner,
        tools: ToolGatewayFactory,
        obo: OboProvider,
        profile: ProfileClient,
        conversations: ConversationStore,
        limiter: RateLimiter,
        agent_kind: Literal["fake", "foundry"] = "foundry",
        agent_name: str = "energy-usage-agent",
        retention_days: int = 30,
        store_kind: str = "postgres",
    ) -> None:
        self._agent = agent
        self._tools = tools
        self._obo = obo
        self._profile = profile
        self._conversations = conversations
        self._limiter = limiter
        self._agent_kind: Literal["fake", "foundry"] = agent_kind
        self._agent_name = agent_name
        self._retention_days = retention_days
        self._store_kind = store_kind

    async def me(self, principal: Principal) -> MeResponse:
        token = await self._obo.token_for(principal)
        me = await self._profile.me(principal, token)
        return MeResponse(
            onboarded=me.onboarded,
            customer_name=me.customer_name,
            timezone=me.timezone,
            user_name=principal.name,
        )

    async def prepare(self, principal: Principal, request: ChatRequest, correlation_id: str) -> PreparedChat:
        """Checks that must fail with a proper HTTP status before any streaming starts."""
        retry_after = self._limiter.hit(principal.key)
        if retry_after is not None:
            raise RateLimited(retry_after)
        message = request.message.strip()
        token = await self._obo.token_for(principal)
        if not (await self._profile.me(principal, token)).onboarded:
            raise NotOnboarded("Your account is not linked to a customer yet. Contact your administrator.")
        conversation = None
        if request.conversation_id:
            conversation = await self._conversations.get(
                request.conversation_id, principal.tid, principal.oid
            )
            if conversation is None:  # someone else's conversation looks exactly like a missing one
                raise ConversationNotFound()
        return PreparedChat(principal, message, token, conversation, correlation_id)

    async def answer(self, chat: PreparedChat, emit: Emit = no_emit) -> ChatResponse:
        started = time.perf_counter()
        await emit("status", {"stage": "thinking"})
        prior = chat.conversation.agent_conversation_id if chat.conversation else None
        async with self._tools.open(chat.user_token, chat.correlation_id) as inner:
            gateway = TimedGateway(inner)
            try:
                turn = await self._agent.run_turn(chat.message, prior, gateway, emit)
            except AgentLoopLimit as exc:
                _log.warning("agent_loop_limit", extra={"event": "agent_loop_limit"})
                agent_conversation_id = str(exc.args[0]) if exc.args else prior
                conversation = await self._save(chat, agent_conversation_id)
                return await self._record(
                    chat,
                    conversation,
                    self._response(chat, conversation, started, "error", LOOP_LIMIT_ANSWER, gateway.calls),
                )
        await emit("status", {"stage": "composing"})
        conversation = await self._save(chat, turn.agent_conversation_id)
        view = project(turn.output, turn.calls)
        _log.info(
            "chat_turn",
            extra={
                "event": "chat_turn",
                "status": turn.output.status,
                "tool_calls": len(gateway.calls),
                "tool_errors": sum(1 for c in gateway.calls if c.error),
            },
        )
        response = self._response(
            chat,
            conversation,
            started,
            turn.output.status,
            turn.output.answer,
            gateway.calls,
            view,
            turn.output.result_ids,
        )
        return await self._record(chat, conversation, response)

    def _response(
        self,
        chat: PreparedChat,
        conversation: ConversationRecord,
        started: float,
        status: ChatStatus,
        answer: str,
        calls: list[ToolCall],
        view: View | None = None,
        result_ids: list[str] | None = None,
    ) -> ChatResponse:
        trace = build_trace(
            agent=self._agent_kind,
            agent_name=self._agent_name,
            duration_ms=round((time.perf_counter() - started) * 1000),
            status=status,
            calls=calls,
            view=view,
            result_ids=result_ids,
        )
        return ChatResponse(
            answer=answer,
            status=status,
            table=TableData(**view.table) if view and view.table else None,
            chart=ChartData(**view.chart) if view and view.chart else None,
            assumptions=view.assumptions if view else [],
            conversation_id=conversation.conversation_id,
            correlation_id=chat.correlation_id,
            created_at=datetime.now(UTC),
            trace=trace,
        )

    async def _record(
        self, chat: PreparedChat, conversation: ConversationRecord, response: ChatResponse
    ) -> ChatResponse:
        """Keep the turn exactly as shown so a reopened conversation looks the same (retention applies)."""
        try:
            await self._conversations.add_turn(
                conversation.conversation_id,
                StoredTurn(chat.message, response.model_dump(mode="json", by_alias=True)),
            )
        except Exception:  # the user still gets the answer; only history misses this turn
            _log.warning("turn_save_failed", exc_info=True)
        return response

    async def ask(self, principal: Principal, request: ChatRequest, correlation_id: str) -> ChatResponse:
        return await self.answer(await self.prepare(principal, request, correlation_id))

    async def _save(self, chat: PreparedChat, agent_conversation_id: str | None) -> ConversationRecord:
        if chat.conversation:
            await self._conversations.touch(chat.conversation.conversation_id)
            return chat.conversation
        p = chat.principal
        return await self._conversations.create(
            p.tid, p.oid, agent_conversation_id or "", _title(chat.message)
        )

    async def list_conversations(self, principal: Principal) -> list[ConversationSummary]:
        await self.purge_expired()
        rows = await self._conversations.list(principal.tid, principal.oid)
        return [
            ConversationSummary(
                conversation_id=r.conversation_id,
                title=r.title,
                created_at=r.created_at,
                updated_at=r.updated_at,
                turn_count=r.turn_count,
            )
            for r in rows
        ]

    async def get_conversation(self, principal: Principal, conversation_id: UUID) -> ConversationDetail:
        record = await self._conversations.get(conversation_id, principal.tid, principal.oid)
        if record is None or record.updated_at < self._cutoff():
            raise ConversationNotFound()
        turns = await self._conversations.turns(conversation_id)
        return ConversationDetail(
            conversation_id=record.conversation_id,
            title=record.title,
            created_at=record.created_at,
            updated_at=record.updated_at,
            turns=[
                ConversationTurn(question=t.question, response=ChatResponse.model_validate(t.response))
                for t in turns
            ],
        )

    async def purge_expired(self) -> int:
        """Retention: drop conversations idle longer than the retention period (and their agent threads)."""
        try:
            expired = await self._conversations.purge(self._cutoff())
        except Exception:
            _log.warning("history_purge_failed", exc_info=True)
            return 0
        for record in expired:
            await self._forget(record)
        return len(expired)

    async def status(self) -> StatusResponse:
        energy_ok = await self._profile.ready()
        try:
            await self._conversations.ping()
            db_ok = True
        except Exception:
            db_ok = False
        agent_detail = (
            "Fake keyword agent (local only)"
            if self._agent_kind == "fake"
            else f"Foundry prompt agent {self._agent_name}"
        )
        db_detail = "Conversation history" + (" (in memory)" if self._store_kind == "memory" else "")
        return StatusResponse(
            components=[
                StatusComponent(id="api", label="API", status="ok", detail="app-api"),
                StatusComponent(
                    id="energy",
                    label="Energy data",
                    status="ok" if energy_ok else "down",
                    detail="energy-service (REST + MCP)",
                ),
                StatusComponent(
                    id="database", label="History", status="ok" if db_ok else "down", detail=db_detail
                ),
                StatusComponent(id="agent", label="Agent", status="ok", detail=agent_detail),
            ],
            history_retention_days=self._retention_days,
        )

    def _cutoff(self) -> datetime:
        return datetime.now(UTC) - timedelta(days=self._retention_days)

    async def delete_conversation(self, principal: Principal, conversation_id) -> None:  # type: ignore[no-untyped-def]
        record = await self._conversations.delete(conversation_id, principal.tid, principal.oid)
        if record is None:
            raise ConversationNotFound()
        await self._forget(record)

    async def _forget(self, record: ConversationRecord) -> None:
        if record.agent_conversation_id:
            try:
                await self._agent.forget(record.agent_conversation_id)
            except Exception:  # best effort; our record is already gone
                _log.warning("agent_conversation_delete_failed", exc_info=True)


def _title(message: str) -> str:
    one_line = " ".join(message.split())
    return one_line if len(one_line) <= 60 else one_line[:57].rstrip() + "..."
