"""Synthetic, made-up data for local dev, tests and the seed script. No real customers or readings."""

import math
import random
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from energy_usage_shared.auth.dev import DEV_USERS


@dataclass(frozen=True)
class SynthMeter:
    meter_id: str
    name: str
    type: str
    base_kw: float


@dataclass(frozen=True)
class SynthSite:
    site_id: str
    name: str
    city: str
    meters: tuple[SynthMeter, ...]


@dataclass(frozen=True)
class SynthCustomer:
    customer_id: UUID
    name: str
    timezone: str
    users: tuple[tuple[str, str], ...]
    sites: tuple[SynthSite, ...]
    gap_days_ago: tuple[tuple[int, int], ...] = field(default_factory=tuple)

    def meters(self) -> Iterator[tuple[SynthSite, SynthMeter]]:
        for s in self.sites:
            for m in s.meters:
                yield s, m


def _user(uid: str) -> tuple[str, str]:
    u = DEV_USERS[uid]
    return (u.tid, u.oid)


CUSTOMERS: tuple[SynthCustomer, ...] = (
    SynthCustomer(
        UUID("c0000000-0000-4000-8000-000000000001"),
        "Demo Customer 1",
        "America/Chicago",
        (_user("a1"),),
        (
            SynthSite(
                "S-101",
                "North Site",
                "Metro A",
                (
                    SynthMeter("M-1011", "Main", "electric", 42.0),
                    SynthMeter("M-1012", "HVAC", "electric", 18.0),
                ),
            ),
            SynthSite("S-102", "South Site", "Metro B", (SynthMeter("M-1021", "Main", "electric", 30.0),)),
        ),
        gap_days_ago=((40, 42),),
    ),
    SynthCustomer(
        UUID("c0000000-0000-4000-8000-000000000002"),
        "Demo Customer 2",
        "America/New_York",
        (_user("a2"),),
        (
            SynthSite(
                "S-201",
                "Head Office",
                "Metro C",
                (
                    SynthMeter("M-2011", "Main", "electric", 25.0),
                    SynthMeter("M-2012", "Lighting", "electric", 6.0),
                ),
            ),
        ),
        gap_days_ago=((95, 95),),
    ),
    SynthCustomer(
        UUID("c0000000-0000-4000-8000-000000000003"),
        "Demo Customer 3",
        "Europe/London",
        (_user("b1"),),
        (SynthSite("S-301", "Depot", "Metro D", (SynthMeter("M-3011", "Main", "electric", 55.0),)),),
        gap_days_ago=((10, 11),),
    ),
)

_HOUR_PROFILE = [0.55, 0.5, 0.5, 0.5, 0.55, 0.65, 0.85, 1.05, 1.2, 1.25, 1.3, 1.3,
                 1.28, 1.3, 1.3, 1.28, 1.2, 1.1, 1.0, 0.9, 0.8, 0.7, 0.62, 0.58]  # fmt: skip


def _gap_days(customer: SynthCustomer, end_day: date) -> set[date]:
    out: set[date] = set()
    for a, b in customer.gap_days_ago:
        for n in range(min(a, b), max(a, b) + 1):
            out.add(end_day - timedelta(days=n))
    return out


def iter_readings(
    customer: SynthCustomer, start_day: date, end_day: date, step_minutes: int = 15
) -> Iterator[tuple[str, str, datetime, float]]:
    """Yield (site_id, meter_id, ts_utc, kwh) for each interval in [start_day, end_day] local time."""
    tz = ZoneInfo(customer.timezone)
    gaps = _gap_days(customer, end_day)
    for site, meter in customer.meters():
        rng = random.Random(f"{customer.customer_id}:{meter.meter_id}:{start_day.isoformat()}")
        day = start_day
        while day <= end_day:
            if day not in gaps:
                season = 1.0 + 0.25 * math.cos((day.timetuple().tm_yday - 200) / 365 * 2 * math.pi)
                weekday = 0.7 if day.weekday() >= 5 else 1.0
                # Step in UTC so DST days have 23 or 25 hours of intervals, never duplicates.
                ts = datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)
                next_midnight = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC)
                while ts < next_midnight:
                    hour = ts.astimezone(tz).hour
                    kw = meter.base_kw * season * weekday * _HOUR_PROFILE[hour] * rng.uniform(0.9, 1.1)
                    yield (site.site_id, meter.meter_id, ts, round(kw * step_minutes / 60, 4))
                    ts += timedelta(minutes=step_minutes)
            day += timedelta(days=1)
