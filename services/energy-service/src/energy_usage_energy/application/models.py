from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID


class Granularity(StrEnum):
    HOUR = "hour"
    DAY = "day"
    MONTH = "month"


class BreakdownGranularity(StrEnum):
    TOTAL = "total"
    DAY = "day"
    MONTH = "month"


class GroupBy(StrEnum):
    SITE = "site"
    METER = "meter"


class Order(StrEnum):
    MAX = "max"
    MIN = "min"


@dataclass(frozen=True)
class Caller:
    """Identity claims only. Mapping to a customer happens in UsageService via CustomerDirectory."""

    tid: str
    oid: str


@dataclass(frozen=True)
class CustomerContext:
    customer_id: UUID
    name: str
    timezone: str


@dataclass(frozen=True)
class DateRange:
    """Inclusive local dates plus the matching half-open UTC instants [start_utc, end_utc)."""

    start: date
    end: date
    start_utc: datetime
    end_utc: datetime
    tz: str
    partial: bool = False

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def label(self) -> str:
        return f"{self.start.isoformat()} to {self.end.isoformat()}"


@dataclass(frozen=True)
class SeriesQuery:
    range: DateRange
    granularity: Granularity
    site_id: str | None = None
    meter_id: str | None = None


@dataclass(frozen=True)
class Point:
    period: datetime | date
    kwh: float


@dataclass(frozen=True)
class GroupPoint:
    group_id: str
    group_name: str
    period: date | None
    kwh: float


@dataclass(frozen=True)
class MeterInfo:
    site_id: str
    site_name: str
    city: str | None
    meter_id: str
    meter_name: str
    meter_type: str | None
