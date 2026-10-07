"""In-memory conversation store for local dev and tests (same ownership semantics as Postgres)."""

from __future__ import annotations

import builtins
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ..application.models import ConversationRecord, StoredTurn


class MemoryConversationStore:
    def __init__(self) -> None:
        self._items: dict[UUID, ConversationRecord] = {}
        self._turns: dict[UUID, list[StoredTurn]] = {}

    async def create(self, tid: str, oid: str, agent_conversation_id: str, title: str) -> ConversationRecord:
        now = datetime.now(UTC)
        rec = ConversationRecord(uuid4(), tid.lower(), oid.lower(), agent_conversation_id, title, now, now)
        self._items[rec.conversation_id] = rec
        return rec

    async def get(self, conversation_id: UUID, tid: str, oid: str) -> ConversationRecord | None:
        rec = self._items.get(conversation_id)
        return rec if rec and (rec.tid, rec.oid) == (tid.lower(), oid.lower()) else None

    async def touch(self, conversation_id: UUID) -> None:
        if rec := self._items.get(conversation_id):
            self._items[conversation_id] = replace(rec, updated_at=datetime.now(UTC))

    async def set_agent_conversation(self, conversation_id: UUID, agent_conversation_id: str) -> None:
        if rec := self._items.get(conversation_id):
            self._items[conversation_id] = replace(
                rec, agent_conversation_id=agent_conversation_id, updated_at=datetime.now(UTC)
            )

    async def list(self, tid: str, oid: str, limit: int = 50) -> builtins.list[ConversationRecord]:
        mine = [
            replace(r, turn_count=len(self._turns.get(r.conversation_id, [])))
            for r in self._items.values()
            if (r.tid, r.oid) == (tid.lower(), oid.lower())
        ]
        return sorted(mine, key=lambda r: r.updated_at, reverse=True)[:limit]

    async def delete(self, conversation_id: UUID, tid: str, oid: str) -> ConversationRecord | None:
        rec = await self.get(conversation_id, tid, oid)
        if rec:
            del self._items[conversation_id]
            self._turns.pop(conversation_id, None)
        return rec

    async def add_turn(self, conversation_id: UUID, turn: StoredTurn) -> None:
        self._turns.setdefault(conversation_id, []).append(turn)
        await self.touch(conversation_id)

    async def turns(self, conversation_id: UUID) -> builtins.list[StoredTurn]:
        return list(self._turns.get(conversation_id, []))

    async def purge(self, before: datetime, limit: int) -> builtins.list[ConversationRecord]:
        expired = sorted(
            (r for r in self._items.values() if r.updated_at < before), key=lambda r: r.updated_at
        )
        expired = expired[:limit]
        for r in expired:
            del self._items[r.conversation_id]
            self._turns.pop(r.conversation_id, None)
        return expired

    async def ping(self) -> None:
        return None
