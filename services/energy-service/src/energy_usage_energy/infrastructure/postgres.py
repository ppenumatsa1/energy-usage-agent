"""Postgres adapters. Every customer query runs inside RlsSession (BR-3): a transaction with
`set_config('app.customer_id', ..., true)` (= SET LOCAL). RLS policies then filter every table."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from ..application.models import (
    BreakdownGranularity,
    CustomerContext,
    DateRange,
    Granularity,
    GroupBy,
    GroupPoint,
    MeterInfo,
    Point,
    SeriesQuery,
)
from . import queries


class PgCustomerDirectory:
    """Reads the mapping only through the SECURITY DEFINER function energy.resolve_customer."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def resolve(self, tid: str, oid: str) -> CustomerContext | None:
        try:
            UUID(tid), UUID(oid)
        except ValueError:
            return None
        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(queries.RESOLVE_CUSTOMER, {"tid": tid, "oid": oid})
            row = await cur.fetchone()
        if not row:
            return None
        return CustomerContext(customer_id=row["customer_id"], name=row["name"], timezone=row["timezone"])


class PgUsageReader:
    def __init__(self, conn: AsyncConnection[Any]) -> None:
        self._conn = conn

    async def _fetch(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)  # type: ignore[arg-type]
            return await cur.fetchall()

    async def series(self, query: SeriesQuery) -> list[Point]:
        rng = query.range
        params: dict[str, Any] = {"site_id": query.site_id, "meter_id": query.meter_id}
        if query.granularity == Granularity.HOUR:
            params |= {"tz": rng.tz, "start_utc": rng.start_utc, "end_utc": rng.end_utc}
            rows = await self._fetch(queries.SERIES_HOURLY, params)
        else:
            params |= {"unit": query.granularity.value, "start": rng.start, "end": rng.end}
            rows = await self._fetch(queries.SERIES_DAILY, params)
        return [Point(period=r["period"], kwh=r["kwh"]) for r in rows]

    async def breakdown(
        self, rng: DateRange, group_by: GroupBy, granularity: BreakdownGranularity
    ) -> list[GroupPoint]:
        sql = queries.BREAKDOWN_SITE if group_by == GroupBy.SITE else queries.BREAKDOWN_METER
        unit = granularity.value
        params = {
            "unit": unit,
            "unit_or_day": "day" if unit == "total" else unit,
            "start": rng.start,
            "end": rng.end,
        }
        rows = await self._fetch(sql, params)
        return [GroupPoint(r["group_id"], r["group_name"], r["period"], r["kwh"]) for r in rows]

    async def sites_and_meters(self) -> list[MeterInfo]:
        rows = await self._fetch(queries.SITES_AND_METERS, {})
        return [MeterInfo(**r) for r in rows]

    async def days_with_data(self, start: date, end: date) -> set[date]:
        rows = await self._fetch(queries.DAYS_WITH_DATA, {"start": start, "end": end})
        return {r["day"] for r in rows}


class PgUsageRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @asynccontextmanager
    async def scoped(self, customer_id: UUID) -> AsyncIterator[PgUsageReader]:
        async with rls_session(self._pool, customer_id) as conn:
            yield PgUsageReader(conn)

    async def ping(self) -> bool:
        async with self._pool.connection() as conn:
            await conn.execute("SELECT 1")
        return True


@asynccontextmanager
async def rls_session(pool: AsyncConnectionPool, customer_id: UUID) -> AsyncIterator[AsyncConnection[Any]]:
    """The ONLY way to get a connection for customer data. Scope is transaction-local, so it cannot
    leak to the next borrower of the pooled connection."""
    if not isinstance(customer_id, UUID):
        raise TypeError("customer_id must be a UUID")
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("SET TRANSACTION READ ONLY")
        await conn.execute(queries.SET_CUSTOMER_SCOPE, {"customer_id": str(customer_id)})
        yield conn
