from datetime import UTC, date, datetime

import pytest

from energy_usage_energy.application.dates import missing_spans, resolve_range
from energy_usage_energy.application.errors import InvalidRange

NOW = datetime(2026, 3, 15, 18, 0, tzinfo=UTC)  # Sunday
TZ = "America/Chicago"


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("last_month", "last_month", (date(2026, 2, 1), date(2026, 2, 28))),
        ("last_week", "last_week", (date(2026, 3, 2), date(2026, 3, 8))),  # weeks start Monday
        ("yesterday", "yesterday", (date(2026, 3, 14), date(2026, 3, 14))),
        ("2026-01", "2026-02", (date(2026, 1, 1), date(2026, 2, 28))),
        ("2026-01-05", "2026-01-07", (date(2026, 1, 5), date(2026, 1, 7))),
    ],
)
def test_resolves_closed_periods(start: str, end: str, expected: tuple[date, date]) -> None:
    rng, _ = resolve_range(start, end, TZ, NOW)
    assert (rng.start, rng.end) == expected
    assert not rng.partial


def test_rolling_windows_include_today() -> None:
    rng, _ = resolve_range("last_7_days", "last_7_days", TZ, NOW)
    assert (rng.start, rng.end, rng.partial) == (date(2026, 3, 9), date(2026, 3, 15), True)
    rng, _ = resolve_range("last_90_days", "last_90_days", TZ, NOW)
    assert (rng.start, rng.end) == (date(2025, 12, 16), date(2026, 3, 15))


def test_this_month_is_partial_and_capped_to_today() -> None:
    rng, notes = resolve_range("this_month", "this_month", TZ, NOW)
    assert (rng.start, rng.end, rng.partial) == (date(2026, 3, 1), date(2026, 3, 15), True)
    assert any("in progress" in n for n in notes)


def test_utc_bounds_follow_local_midnight_across_dst() -> None:
    rng, _ = resolve_range("2026-03-08", "2026-03-08", TZ, NOW)
    assert rng.start_utc == datetime(2026, 3, 8, 6, tzinfo=UTC)  # CST
    assert rng.end_utc == datetime(2026, 3, 9, 5, tzinfo=UTC)  # CDT: a 23-hour day


def test_local_today_differs_from_utc_today() -> None:
    late = datetime(2026, 3, 16, 3, 0, tzinfo=UTC)  # still the 15th in Chicago
    rng, _ = resolve_range("today", "today", TZ, late)
    assert rng.start == date(2026, 3, 15)


def test_range_capped_to_13_months() -> None:
    rng, notes = resolve_range("2020-01-01", "2026-03-14", TZ, NOW)
    assert rng.start == date(2025, 2, 15)
    assert any("13 months" in n for n in notes)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2027-01-01", "2027-01-02"),
        ("2026-03-10", "2026-03-01"),
        ("someday", "today"),
        ("2026-02-30", "today"),
    ],
)
def test_invalid_ranges(start: str, end: str) -> None:
    with pytest.raises(InvalidRange):
        resolve_range(start, end, TZ, NOW)


def test_missing_spans() -> None:
    present = {date(2026, 1, d) for d in (1, 2, 5, 7)}
    assert missing_spans(date(2026, 1, 1), date(2026, 1, 7), present) == [
        (date(2026, 1, 3), date(2026, 1, 4)),
        (date(2026, 1, 6), date(2026, 1, 6)),
    ]
