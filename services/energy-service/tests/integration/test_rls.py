"""BR-3: the database itself enforces customer isolation for the app role."""

import psycopg
import pytest

from energy_usage_energy.application.errors import DataUnavailable, InvalidArgument, QueryTimeout
from energy_usage_energy.application.models import Caller, Granularity
from energy_usage_energy.application.service import UsageService
from energy_usage_energy.infrastructure.postgres import PgCustomerDirectory, PgUsageRepository, rls_session
from energy_usage_energy.testing.synthetic import CUSTOMERS
from energy_usage_shared.auth import DEV_USERS
from energy_usage_shared.db import build_pool

C1, C2, C3 = (c.customer_id for c in CUSTOMERS)
TABLES = ("sites", "meters", "usage_readings", "usage_daily")


def _count(conn: psycopg.Connection, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM energy.{table}").fetchone()[0]  # type: ignore[index]  # noqa: S608


def test_no_scope_sees_nothing(database: dict[str, str]) -> None:
    with psycopg.connect(database["app"]) as conn:
        for t in TABLES:
            assert _count(conn, t) == 0, t


def test_scope_sees_only_own_rows(database: dict[str, str]) -> None:
    with psycopg.connect(database["app"]) as conn:
        conn.execute("SELECT set_config('app.customer_id', %s, false)", (str(C1),))
        for t in TABLES:
            assert _count(conn, t) > 0, t
            others = conn.execute(
                f"SELECT count(*) FROM energy.{t} WHERE customer_id <> %s",  # noqa: S608
                (C1,),
            ).fetchone()[0]  # type: ignore[index]
            assert others == 0, t


def test_garbage_scope_fails_closed(database: dict[str, str]) -> None:
    with psycopg.connect(database["app"]) as conn:
        conn.execute("SELECT set_config('app.customer_id', '', false)")
        assert _count(conn, "usage_daily") == 0


def test_app_role_cannot_read_mapping_or_write(database: dict[str, str]) -> None:
    with psycopg.connect(database["app"], autocommit=True) as conn:
        for stmt in (
            "SELECT * FROM energy.customers",
            "SELECT * FROM energy.user_customer",
            "DELETE FROM energy.usage_daily",
            "ALTER TABLE energy.usage_daily DISABLE ROW LEVEL SECURITY",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(stmt)  # type: ignore[arg-type]


def test_resolve_customer_function(database: dict[str, str]) -> None:
    u = DEV_USERS["b1"]
    with psycopg.connect(database["app"]) as conn:
        row = conn.execute(
            "SELECT customer_id FROM energy.resolve_customer(%s, %s)", (u.tid, u.oid)
        ).fetchone()
        assert row is not None and row[0] == C3
        x = DEV_USERS["x1"]
        assert (
            conn.execute("SELECT * FROM energy.resolve_customer(%s, %s)", (x.tid, x.oid)).fetchone() is None
        )


async def test_scope_does_not_leak_to_next_pool_borrower(database: dict[str, str]) -> None:
    pool = build_pool(database_url=database["app"], host=None, dbname=None, user=None, entra_auth=False,
                      client_id=None, min_size=1, max_size=1)  # fmt: skip
    async with pool:
        async with rls_session(pool, C1) as conn:
            cur = await conn.execute("SELECT count(*) FROM energy.usage_daily")
            assert (await cur.fetchone())[0] > 0  # type: ignore[index]
            with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                await conn.execute("CREATE TEMP TABLE t (x int)")
        async with pool.connection() as conn:  # same physical connection, scope must be gone
            cur = await conn.execute("SELECT count(*) FROM energy.usage_daily")
            assert (await cur.fetchone())[0] == 0  # type: ignore[index]


async def test_service_end_to_end_on_postgres(database: dict[str, str]) -> None:
    pool = build_pool(database_url=database["app"], host=None, dbname=None, user=None, entra_auth=False,
                      client_id=None)  # fmt: skip
    async with pool:
        svc = UsageService(PgCustomerDirectory(pool), PgUsageRepository(pool))
        a1 = Caller(DEV_USERS["a1"].tid, DEV_USERS["a1"].oid)
        b1 = Caller(DEV_USERS["b1"].tid, DEV_USERS["b1"].oid)
        r = await svc.get_usage(a1, "last_7_days", "last_7_days", Granularity.DAY)
        assert r.rows and r.tz == "America/Chicago"
        hourly = await svc.get_usage(b1, "yesterday", "yesterday", Granularity.HOUR)
        assert 23 <= len(hourly.rows) <= 25
        fall_back = await svc.get_usage(a1, "2025-11-02", "2025-11-02", Granularity.HOUR)
        assert [row["period"] for row in fall_back.rows][1:3] == [
            "2025-11-02 01:00 CDT",
            "2025-11-02 01:00 CST",
        ]
        sites = await svc.list_sites_and_meters(b1)
        assert {row["site_id"] for row in sites.rows} == {"S-301"}
        with pytest.raises(InvalidArgument):
            await svc.get_usage(b1, "last_7_days", "last_7_days", Granularity.DAY, site_id="S-101")
        assert (await svc.me(b1)).customer_name == "Demo Customer 3"


async def test_statement_timeout_is_transaction_local_and_mapped(database: dict[str, str]) -> None:
    pool = build_pool(database_url=database["app"], host=None, dbname=None, user=None, entra_auth=False,
                      client_id=None, min_size=1, max_size=1)  # fmt: skip
    async with pool:
        async with pool.connection() as conn:
            default = (await (await conn.execute("SHOW statement_timeout")).fetchone())[0]  # type: ignore[index]
        with pytest.raises(QueryTimeout):
            async with rls_session(pool, C1, statement_timeout_ms=100) as conn:
                await conn.execute("SELECT pg_sleep(2)")
        async with rls_session(pool, C1) as conn:
            cur = await conn.execute("SHOW statement_timeout")
            assert (await cur.fetchone())[0] == "10s"  # type: ignore[index]
        async with pool.connection() as conn:  # same physical connection, back to the server default
            cur = await conn.execute("SHOW statement_timeout")
            assert (await cur.fetchone())[0] == default  # type: ignore[index]


async def test_unreachable_database_is_unavailable_not_500(database: dict[str, str]) -> None:
    params = psycopg.conninfo.conninfo_to_dict(database["app"])
    bad = psycopg.conninfo.make_conninfo(**{**params, "host": "127.0.0.1", "port": "1"})
    pool = build_pool(database_url=bad, host=None, dbname=None, user=None, entra_auth=False, client_id=None,
                      connect_timeout=1, timeout=0.5)  # fmt: skip
    await pool.open(wait=False)
    try:
        svc = UsageService(PgCustomerDirectory(pool), PgUsageRepository(pool))
        with pytest.raises(DataUnavailable):
            await svc.me(Caller(DEV_USERS["a1"].tid, DEV_USERS["a1"].oid))
        assert await PgUsageRepository(pool).ping() is False
    finally:
        await pool.close()
