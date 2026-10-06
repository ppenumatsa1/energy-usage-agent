"""PgConversationStore on real Postgres, connected as a login that only has app_api_rw (checks grants)."""

import os
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from psycopg import conninfo, sql
from psycopg_pool import AsyncConnectionPool

from energy_usage_app_api.application.models import StoredTurn
from energy_usage_app_api.infrastructure.conversations_pg import PgConversationStore

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"
LOGIN, PASSWORD = "app_api_it_login", "it-only-password"  # throwaway role in a throwaway database
TID, OID, OTHER = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())


@pytest.fixture(scope="module")
def app_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    admin = os.environ.get("TEST_DATABASE_URL")
    server = None
    if not admin:
        pgserver = pytest.importorskip("pgserver")
        server = pgserver.get_server(str(tmp_path_factory.mktemp("pg")), cleanup_mode="stop")
        admin = server.get_uri()
    name = f"app_api_it_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    params = conninfo.conninfo_to_dict(admin)
    with psycopg.connect(conninfo.make_conninfo(**{**params, "dbname": name}), autocommit=True) as c:
        for f in sorted(MIGRATIONS.glob("*.sql")):
            c.execute(f.read_text())  # type: ignore[arg-type]
        if not c.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (LOGIN,)).fetchone():
            c.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(LOGIN), sql.Literal(PASSWORD)
                )
            )
        c.execute(sql.SQL("GRANT app_api_rw TO {}").format(sql.Identifier(LOGIN)))
    try:
        yield conninfo.make_conninfo(**{**params, "dbname": name, "user": LOGIN, "password": PASSWORD})
    finally:
        with psycopg.connect(admin, autocommit=True) as c:
            c.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        if server:
            server.cleanup()


@pytest.fixture
async def store(app_url: str) -> AsyncIterator[PgConversationStore]:
    async with AsyncConnectionPool(app_url, min_size=1, max_size=2, open=False) as pool:
        yield PgConversationStore(pool)


async def test_turns_round_trip_with_owner_scoping(store: PgConversationStore) -> None:
    await store.ping()
    rec = await store.create(TID, OID, "agent-conv-1", "usage last month")
    await store.add_turn(rec.conversation_id, StoredTurn("q1", {"answer": "a1", "table": {"rows": [1, 2]}}))
    await store.add_turn(rec.conversation_id, StoredTurn("q2", {"answer": "a2"}))
    assert [t.question for t in await store.turns(rec.conversation_id)] == ["q1", "q2"]
    assert (await store.turns(rec.conversation_id))[0].response["table"]["rows"] == [1, 2]
    listed = await store.list(TID, OID)
    assert listed[0].conversation_id == rec.conversation_id and listed[0].turn_count == 2
    assert listed[0].updated_at > rec.updated_at
    assert await store.list(TID, OTHER) == []
    assert await store.get(rec.conversation_id, TID, OTHER) is None
    assert await store.delete(rec.conversation_id, TID, OID) is not None
    assert await store.turns(rec.conversation_id) == []  # cascade


async def test_purge_removes_idle_conversations_and_turns(store: PgConversationStore) -> None:
    old = await store.create(TID, OID, "agent-old", "old")
    await store.add_turn(old.conversation_id, StoredTurn("q", {"answer": "a"}))
    fresh = await store.create(TID, OID, "agent-new", "new")
    purged = await store.purge(datetime.now(UTC) + timedelta(seconds=1))
    assert {r.conversation_id for r in purged} >= {old.conversation_id, fresh.conversation_id}
    assert await store.turns(old.conversation_id) == []
    keep = await store.create(TID, OID, "agent-keep", "keep")
    assert await store.purge(datetime.now(UTC) - timedelta(days=30)) == []
    assert await store.get(keep.conversation_id, TID, OID) is not None
