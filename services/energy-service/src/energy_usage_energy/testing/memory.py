"""In-memory directory + repository with the same scoping semantics as RLS (one customer per session)."""

from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from functools import lru_cache
from uuid import UUID
from zoneinfo import ZoneInfo

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
from .synthetic import CUSTOMERS, SynthCustomer


class _CustomerData:
    def __init__(self, customer: SynthCustomer, start: date, end: date) -> None:
        self.customer = customer
        tz = ZoneInfo(customer.timezone)
        self.daily: dict[tuple[str, str, date], float] = defaultdict(float)
        self.hourly: dict[tuple[str, str, datetime], float] = defaultdict(float)
        for site_id, meter_id, ts, kwh in iter_hourly(customer, start, end):
            local = ts.astimezone(tz)
            self.daily[(site_id, meter_id, local.date())] += kwh
            self.hourly[(site_id, meter_id, local.replace(minute=0, tzinfo=None))] += kwh


def iter_hourly(customer: SynthCustomer, start: date, end: date):  # type: ignore[no-untyped-def]
    from .synthetic import iter_readings

    return iter_readings(customer, start, end, step_minutes=60)


@lru_cache(maxsize=8)
def _dataset(end_day: date, days: int) -> dict[UUID, _CustomerData]:
    start = end_day - timedelta(days=days)
    return {c.customer_id: _CustomerData(c, start, end_day) for c in CUSTOMERS}


class MemoryDirectory:
    def __init__(self, customers: tuple[SynthCustomer, ...] = CUSTOMERS) -> None:
        self._map = {
            (tid, oid): CustomerContext(c.customer_id, c.name, c.timezone)
            for c in customers
            for tid, oid in c.users
        }

    async def resolve(self, tid: str, oid: str) -> CustomerContext | None:
        return self._map.get((tid.lower(), oid.lower()))


def _trunc(d: date, g: Granularity | BreakdownGranularity) -> date:
    return d.replace(day=1) if g in (Granularity.MONTH, BreakdownGranularity.MONTH) else d


class MemoryReader:
    def __init__(self, data: _CustomerData) -> None:
        self._d = data

    def _match(self, site: str, meter: str, q: SeriesQuery) -> bool:
        return (q.site_id is None or site == q.site_id) and (q.meter_id is None or meter == q.meter_id)

    async def series(self, query: SeriesQuery) -> list[Point]:
        rng, out = query.range, defaultdict(float)
        if query.granularity == Granularity.HOUR:
            for (s, m, h), kwh in self._d.hourly.items():
                if rng.start <= h.date() <= rng.end and self._match(s, m, query):
                    out[h] += kwh
        else:
            for (s, m, d), kwh in self._d.daily.items():
                if rng.start <= d <= rng.end and self._match(s, m, query):
                    out[_trunc(d, query.granularity)] += kwh
        return [Point(k, v) for k, v in sorted(out.items())]

    async def breakdown(
        self, rng: DateRange, group_by: GroupBy, granularity: BreakdownGranularity
    ) -> list[GroupPoint]:
        names = {}
        for site, meter in self._d.customer.meters():
            names[site.site_id] = site.name
            names[meter.meter_id] = meter.name
        out: dict[tuple[str, date | None], float] = defaultdict(float)
        for (s, m, d), kwh in self._d.daily.items():
            if rng.start <= d <= rng.end:
                gid = s if group_by == GroupBy.SITE else m
                period = None if granularity == BreakdownGranularity.TOTAL else _trunc(d, granularity)
                out[(gid, period)] += kwh
        return [
            GroupPoint(gid, names[gid], p, v)
            for (gid, p), v in sorted(out.items(), key=lambda kv: (kv[0][1] or date.min, kv[0][0]))
        ]

    async def sites_and_meters(self) -> list[MeterInfo]:
        return [
            MeterInfo(s.site_id, s.name, s.city, m.meter_id, m.name, m.type)
            for s, m in self._d.customer.meters()
        ]

    async def days_with_data(self, start: date, end: date) -> set[date]:
        return {d for (_, _, d) in self._d.daily if start <= d <= end}


class MemoryRepository:
    def __init__(self, end_day: date, days: int = 400) -> None:
        self._end_day, self._days = end_day, days

    @asynccontextmanager
    async def scoped(self, customer_id: UUID) -> AsyncIterator[MemoryReader]:
        data = _dataset(self._end_day, self._days).get(customer_id)
        if data is None:
            raise LookupError("unknown customer")
        yield MemoryReader(data)

    async def ping(self) -> bool:
        return True
