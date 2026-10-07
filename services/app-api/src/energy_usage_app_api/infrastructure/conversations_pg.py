"""Conversation ownership in Postgres (schema app_api). Every query filters by (tid, oid).
Connection problems (server down, pool timeout) become UpstreamUnavailable (503), never a raw 500."""

from __future__ import annotations

import builtins
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from ..application.errors import UpstreamUnavailable
from ..application.models import ConversationRecord, StoredTurn

_COLS = "conversation_id, tid::text, oid::text, agent_conversation_id, title, created_at, updated_at"


def _rec(row: dict[str, Any]) -> ConversationRecord:
    return ConversationRecord(**row)


_log = logging.getLogger("energy_usage.history")


class PgConversationStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
        try:
            async with self._pool.connection() as conn:
                yield conn
        except (
            psycopg.OperationalError,
            psycopg.InterfaceError,
        ) as exc:  # PoolTimeout is an OperationalError
            _log.warning(
                "history_db_unavailable",
                extra={"event": "history_db_unavailable", "error_type": type(exc).__name__},
            )
            raise UpstreamUnavailable(
                "Conversation history is temporarily unavailable. Try again shortly."
            ) from exc

    async def _one(self, sql: str, params: tuple[Any, ...]) -> ConversationRecord | None:
        async with self._connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(sql, params)  # type: ignore[arg-type]
            row = await cur.fetchone()
        return _rec(row) if row else None

    async def create(self, tid: str, oid: str, agent_conversation_id: str, title: str) -> ConversationRecord:
        rec = await self._one(
            f"INSERT INTO app_api.conversations (conversation_id, tid, oid, agent_conversation_id, title) "  # noqa: S608
            f"VALUES (%s, %s, %s, %s, %s) RETURNING {_COLS}",
            (uuid4(), tid, oid, agent_conversation_id, title),
        )
        assert rec is not None
        return rec

    async def get(self, conversation_id: UUID, tid: str, oid: str) -> ConversationRecord | None:
        return await self._one(
            f"SELECT {_COLS} FROM app_api.conversations WHERE conversation_id=%s AND tid=%s AND oid=%s",  # noqa: S608
            (conversation_id, tid, oid),
        )

    async def touch(self, conversation_id: UUID) -> None:
        async with self._connection() as conn:
            await conn.execute(
                "UPDATE app_api.conversations SET updated_at=%s WHERE conversation_id=%s",
                (datetime.now(UTC), conversation_id),
            )

    async def set_agent_conversation(self, conversation_id: UUID, agent_conversation_id: str) -> None:
        async with self._connection() as conn:
            await conn.execute(
                "UPDATE app_api.conversations SET agent_conversation_id=%s, updated_at=%s WHERE conversation_id=%s",
                (agent_conversation_id, datetime.now(UTC), conversation_id),
            )

    async def list(self, tid: str, oid: str, limit: int = 50) -> builtins.list[ConversationRecord]:
        async with self._connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                f"SELECT {_COLS}, (SELECT count(*) FROM app_api.turns t "  # noqa: S608
                "WHERE t.conversation_id = c.conversation_id)::int AS turn_count "
                "FROM app_api.conversations c WHERE tid=%s AND oid=%s "
                "ORDER BY updated_at DESC LIMIT %s",
                (tid, oid, limit),
            )
            return [_rec(r) for r in await cur.fetchall()]

    async def delete(self, conversation_id: UUID, tid: str, oid: str) -> ConversationRecord | None:
        return await self._one(
            f"DELETE FROM app_api.conversations WHERE conversation_id=%s AND tid=%s AND oid=%s RETURNING {_COLS}",  # noqa: S608
            (conversation_id, tid, oid),
        )

    async def add_turn(self, conversation_id: UUID, turn: StoredTurn) -> None:
        async with self._connection() as conn, conn.transaction():
            await conn.execute(
                "INSERT INTO app_api.turns (conversation_id, question, response) VALUES (%s, %s, %s)",
                (conversation_id, turn.question, Jsonb(turn.response)),
            )
            await conn.execute(
                "UPDATE app_api.conversations SET updated_at=%s WHERE conversation_id=%s",
                (datetime.now(UTC), conversation_id),
            )

    async def turns(self, conversation_id: UUID) -> builtins.list[StoredTurn]:
        """Callers check ownership with get() first."""
        async with self._connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                "SELECT question, response FROM app_api.turns WHERE conversation_id=%s ORDER BY turn_id",
                (conversation_id,),
            )
            return [StoredTurn(r["question"], r["response"]) for r in await cur.fetchall()]

    async def purge(self, before: datetime, limit: int) -> builtins.list[ConversationRecord]:
        # SKIP LOCKED: replicas purging at the same time take disjoint rows instead of waiting.
        async with self._connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                f"DELETE FROM app_api.conversations WHERE conversation_id IN ("  # noqa: S608
                "SELECT conversation_id FROM app_api.conversations WHERE updated_at < %s "
                f"ORDER BY updated_at LIMIT %s FOR UPDATE SKIP LOCKED) RETURNING {_COLS}",
                (before, limit),
            )
            return [_rec(r) for r in await cur.fetchall()]

    async def ping(self) -> None:
        async with self._connection() as conn:
            await conn.execute("SELECT 1")
