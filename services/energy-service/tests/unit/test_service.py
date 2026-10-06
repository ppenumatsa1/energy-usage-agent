import pytest

from energy_usage_energy.application.errors import InvalidArgument, InvalidRange, NotOnboarded
from energy_usage_energy.application.models import BreakdownGranularity, Granularity, GroupBy, Order
from energy_usage_energy.application.service import UsageService


async def test_me(service: UsageService, caller) -> None:
    me = await service.me(caller("a1"))
    assert me.onboarded and me.customer_name == "Demo Customer 1" and me.timezone == "America/Chicago"
    assert not (await service.me(caller("x1"))).onboarded


async def test_not_onboarded_user_gets_no_data(service: UsageService, caller) -> None:
    with pytest.raises(NotOnboarded):
        await service.get_usage(caller("x1"), "last_month", "last_month", Granularity.DAY)


async def test_get_usage_daily(service: UsageService, caller) -> None:
    r = await service.get_usage(caller("a1"), "last_month", "last_month", Granularity.DAY)
    assert r.tool == "get_usage" and r.unit == "kWh" and r.tz == "America/Chicago"
    # Synthetic gap: Customer 1 has no data 40-42 days before DATA_END (2026-01-31..2026-02-02).
    assert len(r.rows) == 26
    assert [c.key for c in r.columns] == ["period", "kwh"]
    assert r.rows[0]["period"] == "2026-02-03"
    assert any("Missing data for: 2026-02-01..2026-02-02" in a for a in r.assumptions)
    assert all(row["kwh"] > 0 for row in r.rows)
    assert r.chart_hint is not None and r.chart_hint.x == "period"
    assert r.result_id.startswith("r_")


async def test_monthly_total_equals_sum_of_days(service: UsageService, caller) -> None:
    daily = await service.get_usage(caller("a1"), "last_month", "last_month", Granularity.DAY)
    monthly = await service.get_usage(caller("a1"), "last_month", "last_month", Granularity.MONTH)
    assert len(monthly.rows) == 1
    assert monthly.rows[0]["kwh"] == pytest.approx(sum(r["kwh"] for r in daily.rows), abs=0.1)


async def test_site_filter_and_unknown_site(service: UsageService, caller) -> None:
    all_ = await service.get_usage(caller("a1"), "last_month", "last_month", Granularity.MONTH)
    north = await service.get_usage(
        caller("a1"), "last_month", "last_month", Granularity.MONTH, site_id="S-101"
    )
    assert 0 < north.rows[0]["kwh"] < all_.rows[0]["kwh"]
    # Another customer's site behaves exactly like a site that does not exist (no existence leak).
    with pytest.raises(InvalidArgument):
        await service.get_usage(caller("a1"), "last_month", "last_month", Granularity.DAY, site_id="S-201")


async def test_hourly_limited_to_31_days(service: UsageService, caller) -> None:
    with pytest.raises(InvalidRange):
        await service.get_usage(caller("a1"), "2026-01-01", "2026-03-01", Granularity.HOUR)
    r = await service.get_usage(caller("a1"), "yesterday", "yesterday", Granularity.HOUR)
    assert len(r.rows) == 24


async def test_compare_month_to_date_is_like_for_like(service: UsageService, caller) -> None:
    r = await service.compare_usage(
        caller("a1"), "this_month", "this_month", "last_month", "last_month", Granularity.DAY
    )
    assert any("like-for-like" in a for a in r.assumptions)
    s = r.summary
    assert s["period_a"] == "2026-03-01 to 2026-03-15" and s["period_b"] == "2026-02-01 to 2026-02-15"
    assert s["delta_kwh"] == pytest.approx(s["total_a_kwh"] - s["total_b_kwh"], abs=0.01)
    # Rows align by position in the period even though Feb 1-2 has no data.
    first = r.rows[0]
    assert (first["step"], first["period_a"], first["period_b"], first["kwh_b"]) == (
        1,
        "2026-03-01",
        None,
        None,
    )
    assert r.rows[2]["period_b"] == "2026-02-03"


async def test_peaks(service: UsageService, caller) -> None:
    top = await service.get_peak_usage(
        caller("a1"), "last_month", "last_month", Granularity.DAY, 3, Order.MAX
    )
    low = await service.get_peak_usage(
        caller("a1"), "last_month", "last_month", Granularity.DAY, 3, Order.MIN
    )
    assert len(top.rows) == 3 and len(low.rows) == 3
    assert top.rows[0]["kwh"] >= top.rows[-1]["kwh"] >= low.rows[-1]["kwh"] >= low.rows[0]["kwh"]


async def test_breakdown_total_shares_sum_to_100(service: UsageService, caller) -> None:
    r = await service.get_usage_breakdown(caller("a1"), "last_month", "last_month", GroupBy.SITE)
    assert {row["group_id"] for row in r.rows} == {"S-101", "S-102"}
    assert sum(row["share_pct"] for row in r.rows) == pytest.approx(100, abs=0.2)


async def test_breakdown_series_is_long_format(service: UsageService, caller) -> None:
    r = await service.get_usage_breakdown(
        caller("a1"), "last_month", "last_month", GroupBy.METER, BreakdownGranularity.DAY
    )
    assert r.chart_hint is not None and r.chart_hint.series == "group"
    assert len(r.rows) == 26 * 3


async def test_sites_and_meters_only_own(service: UsageService, caller) -> None:
    r = await service.list_sites_and_meters(caller("b1"))
    assert {row["meter_id"] for row in r.rows} == {"M-3011"}


async def test_coverage_reports_gaps(service: UsageService, caller) -> None:
    r = await service.get_data_coverage(caller("b1"), "last_30_days", "last_30_days")
    # Customer 3 gap: 10-11 days before DATA_END; today has no data yet.
    assert {"from": "2026-03-03", "to": "2026-03-04", "days": 2} in r.rows
    assert r.summary["days_in_range"] == 30
