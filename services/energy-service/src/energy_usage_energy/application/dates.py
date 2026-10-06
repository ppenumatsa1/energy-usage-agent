"""Server-side date resolution in the customer's time zone (BR-4, BR-7)."""

import re
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .errors import InvalidRange
from .models import DateRange

MAX_MONTHS = 13
MAX_HOURLY_DAYS = 31

KEYWORDS = (
    "today",
    "yesterday",
    "this_week",
    "last_week",
    "this_month",
    "last_month",
    "this_year",
    "last_year",
    "last_7_days",
    "last_30_days",
    "last_90_days",
    "last_12_months",
)
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_MONTH = re.compile(r"^\d{4}-\d{2}$")


def _month_start(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    last_day = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(d.day, last_day))


def _keyword_span(keyword: str, today: date) -> tuple[date, date]:
    monday = today - timedelta(days=today.weekday())
    spans: dict[str, Callable[[], tuple[date, date]]] = {
        "today": lambda: (today, today),
        "yesterday": lambda: (today - timedelta(days=1), today - timedelta(days=1)),
        "this_week": lambda: (monday, today),
        "last_week": lambda: (monday - timedelta(days=7), monday - timedelta(days=1)),
        "this_month": lambda: (_month_start(today), today),
        "last_month": lambda: (
            _month_start(_month_start(today) - timedelta(days=1)),
            _month_start(today) - timedelta(days=1),
        ),
        "this_year": lambda: (date(today.year, 1, 1), today),
        "last_year": lambda: (date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)),
        "last_7_days": lambda: (today - timedelta(days=6), today),
        "last_30_days": lambda: (today - timedelta(days=29), today),
        "last_90_days": lambda: (today - timedelta(days=89), today),
        "last_12_months": lambda: (add_months(today, -12) + timedelta(days=1), today),
    }
    return spans[keyword]()


def _parse_bound(value: str, today: date, is_end: bool) -> date:
    v = value.strip().lower()
    if v in KEYWORDS:
        start, end = _keyword_span(v, today)
        return end if is_end else start
    if _ISO_DATE.match(v):
        try:
            return date.fromisoformat(v)
        except ValueError as exc:
            raise InvalidRange(f"'{value}' is not a valid date") from exc
    if _ISO_MONTH.match(v):
        first = date.fromisoformat(f"{v}-01")
        return add_months(first, 1) - timedelta(days=1) if is_end else first
    raise InvalidRange(
        f"'{value}' is not a valid date. Use YYYY-MM-DD, YYYY-MM or one of: {', '.join(KEYWORDS)}"
    )


def to_utc(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)


def resolve_range(start: str, end: str, tz_name: str, now: datetime) -> tuple[DateRange, list[str]]:
    """Resolve inclusive local dates. Returns the range plus human-readable assumptions."""
    tz = ZoneInfo(tz_name)
    today = now.astimezone(tz).date()
    s = _parse_bound(start, today, is_end=False)
    e = _parse_bound(end, today, is_end=True)
    notes: list[str] = []
    if s > today:
        raise InvalidRange(f"The period starts in the future ({s.isoformat()}).")
    if e < s:
        raise InvalidRange("The end date must be on or after the start date.")
    partial = False
    if e >= today:
        if e > today:
            notes.append(f"End date capped to today ({today.isoformat()}).")
        e, partial = today, True
    earliest = add_months(e, -MAX_MONTHS) + timedelta(days=1)
    if s < earliest:
        notes.append(f"Range capped to {MAX_MONTHS} months; start moved to {earliest.isoformat()}.")
        s = earliest
    rng = DateRange(s, e, to_utc(s, tz), to_utc(e + timedelta(days=1), tz), tz_name, partial)
    if partial:
        notes.append(f"{rng.label()} ({tz_name}); today is still in progress.")
    else:
        notes.append(f"{rng.label()} ({tz_name}).")
    return rng, notes


def truncate(rng: DateRange, days: int) -> DateRange:
    tz = ZoneInfo(rng.tz)
    end = rng.start + timedelta(days=days - 1)
    return DateRange(rng.start, end, rng.start_utc, to_utc(end + timedelta(days=1), tz), rng.tz, rng.partial)


def missing_spans(start: date, end: date, present: set[date]) -> list[tuple[date, date]]:
    spans: list[tuple[date, date]] = []
    cur: date | None = None
    d = start
    while d <= end:
        if d not in present:
            cur = cur or d
        elif cur:
            spans.append((cur, d - timedelta(days=1)))
            cur = None
        d += timedelta(days=1)
    if cur:
        spans.append((cur, end))
    return spans
