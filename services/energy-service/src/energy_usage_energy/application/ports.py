from contextlib import AbstractAsyncContextManager
from datetime import date
from typing import Protocol
from uuid import UUID

from .models import (
    BreakdownGranularity,
    CustomerContext,
    DateRange,
    GroupBy,
    GroupPoint,
    MeterInfo,
    Point,
    SeriesQuery,
)


class CustomerDirectory(Protocol):
    """Sole owner of the (tid, oid) -> customer mapping."""

    async def resolve(self, tid: str, oid: str) -> CustomerContext | None: ...


class UsageReader(Protocol):
    """Reads one customer's data. Implementations must be bound to a customer-scoped (RLS) session."""

    async def series(self, query: SeriesQuery) -> list[Point]: ...

    async def breakdown(
        self, rng: DateRange, group_by: GroupBy, granularity: BreakdownGranularity
    ) -> list[GroupPoint]: ...

    async def sites_and_meters(self) -> list[MeterInfo]: ...

    async def days_with_data(self, start: date, end: date) -> set[date]: ...


class UsageRepository(Protocol):
    def scoped(self, customer_id: UUID) -> AbstractAsyncContextManager[UsageReader]: ...

    async def ping(self) -> bool: ...
