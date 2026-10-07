from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from energy_usage_shared.auth import Principal
from energy_usage_shared.contracts import Me

from .models import AgentTurn, ConversationRecord, Emit, StoredTurn, ToolCall


class ToolGateway(Protocol):
    """Calls energy-service tools as the signed-in user (OBO token). Never raises for tool errors."""

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolCall: ...


class ToolGatewayFactory(Protocol):
    def open(self, user_token: str, correlation_id: str) -> AbstractAsyncContextManager[ToolGateway]: ...


class AgentRunner(Protocol):
    async def run_turn(
        self, message: str, agent_conversation_id: str | None, tools: ToolGateway, emit: Emit
    ) -> AgentTurn: ...

    async def forget(self, agent_conversation_id: str) -> None: ...


class OboProvider(Protocol):
    async def token_for(self, principal: Principal) -> str: ...


class ProfileClient(Protocol):
    async def me(self, principal: Principal, token: str) -> Me: ...
    async def ready(self) -> bool:
        """energy-service readiness (its own DB included). Never raises."""
        ...


class ConversationStore(Protocol):
    """Raises UpstreamUnavailable when the database can't be reached."""

    async def create(
        self, tid: str, oid: str, agent_conversation_id: str, title: str
    ) -> ConversationRecord: ...
    async def get(self, conversation_id: UUID, tid: str, oid: str) -> ConversationRecord | None: ...
    async def touch(self, conversation_id: UUID) -> None: ...
    async def set_agent_conversation(self, conversation_id: UUID, agent_conversation_id: str) -> None:
        """Point the conversation at a new agent thread and bump updated_at."""
        ...

    async def list(self, tid: str, oid: str, limit: int = 50) -> list[ConversationRecord]: ...
    async def delete(self, conversation_id: UUID, tid: str, oid: str) -> ConversationRecord | None: ...
    async def add_turn(self, conversation_id: UUID, turn: StoredTurn) -> None:
        """Append a turn and bump updated_at."""
        ...

    async def turns(self, conversation_id: UUID) -> list[StoredTurn]: ...
    async def purge(self, before: datetime, limit: int) -> list[ConversationRecord]:
        """Delete up to `limit` conversations (and their turns) not updated since `before` (retention).
        Concurrent callers never return the same record twice."""
        ...

    async def ping(self) -> None: ...


class RateLimiter(Protocol):
    def hit(self, key: str) -> int | None:
        """Record a request. Returns seconds to wait if over the limit, else None."""
        ...
