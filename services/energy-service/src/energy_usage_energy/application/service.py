"""UsageService: the one application core behind both the REST (/v1) and MCP (/mcp) adapters."""

import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Any

from energy_usage_shared.contracts import Column, Me, ToolResult
from energy_usage_shared.contracts.tools import ChartHint

from .audit import audit_tool_call
from .dates import MAX_HOURLY_DAYS, missing_spans, resolve_range, truncate
from .errors import EnergyError, InvalidArgument, InvalidRange, NoData, NotOnboarded
from .models import (
    BreakdownGranularity,
    Caller,
    CustomerContext,
    DateRange,
    Granularity,
    GroupBy,
    Order,
    Point,
    SeriesQuery,
)
from .ports import CustomerDirectory, UsageReader, UsageRepository

MAX_TOP_N = 10
MAX_ID_LEN = 64
Clock = Callable[[], datetime]


def _fmt_period(p: datetime | date, granularity: Granularity | BreakdownGranularity) -> str:
    if granularity == Granularity.HOUR and isinstance(p, datetime):
        label = p.strftime("%Y-%m-%d %H:00")
        # The hour repeated on DST fall-back appears twice; the zone name (e.g. CDT/CST) tells them apart.
        if p.replace(fold=0).utcoffset() != p.replace(fold=1).utcoffset():
            label += f" {p.tzname()}"
        return label
    if granularity in (Granularity.MONTH, BreakdownGranularity.MONTH):
        return p.strftime("%Y-%m")
    return p.strftime("%Y-%m-%d")


def _r(x: float) -> float:
    return round(float(x), 3)


def _offset(p: datetime | date, rng: DateRange, granularity: Granularity) -> int:
    """Position of a period within its range, so two periods line up even when one has gaps."""
    if granularity == Granularity.MONTH:
        return (p.year - rng.start.year) * 12 + p.month - rng.start.month
    if granularity == Granularity.HOUR and isinstance(p, datetime):
        return int((p.astimezone(UTC) - rng.start_utc).total_seconds() // 3600)
    day = p.date() if isinstance(p, datetime) else p
    return (day - rng.start).days


def _new_result_id() -> str:
    return f"r_{uuid.uuid4().hex[:10]}"


def _check_id(name: str, value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if len(value) > MAX_ID_LEN or not value.replace("-", "").replace("_", "").isalnum():
        raise InvalidArgument(f"{name} is not a valid identifier.")
    return value


class UsageService:
    def __init__(
        self, directory: CustomerDirectory, repository: UsageRepository, clock: Clock | None = None
    ) -> None:
        self._directory = directory
        self._repo = repository
        self._clock = clock or (lambda: datetime.now(UTC))

    # ---- identity -------------------------------------------------------------------------------
    async def me(self, caller: Caller) -> Me:
        customer = await self._directory.resolve(caller.tid, caller.oid)
        if customer is None:
            return Me(onboarded=False)
        return Me(onboarded=True, customer_name=customer.name, timezone=customer.timezone)

    async def _customer(self, caller: Caller) -> CustomerContext:
        customer = await self._directory.resolve(caller.tid, caller.oid)
        if customer is None:
            raise NotOnboarded("Your account is not linked to a customer yet. Contact your administrator.")
        return customer

    async def _run(
        self,
        caller: Caller,
        tool: str,
        params: dict[str, Any],
        channel: str,
        body: Callable[[CustomerContext, UsageReader], Awaitable[ToolResult]],
    ) -> ToolResult:
        started = time.perf_counter()
        customer: CustomerContext | None = None
        outcome, rows = "ok", 0
        try:
            customer = await self._customer(caller)
            async with self._repo.scoped(customer.customer_id) as reader:
                result = await body(customer, reader)
            rows = len(result.rows)
            return result
        except EnergyError as exc:
            outcome = exc.code
            raise
        except Exception:
            outcome = "error"
            raise
        finally:
            audit_tool_call(
                tid=caller.tid,
                oid=caller.oid,
                customer_id=str(customer.customer_id) if customer else None,
                tool=tool,
                params=params,
                row_count=rows,
                latency_ms=(time.perf_counter() - started) * 1000,
                outcome=outcome,
                channel=channel,
            )

    def _range(self, start: str, end: str, tz: str) -> tuple[DateRange, list[str]]:
        return resolve_range(start, end, tz, self._clock())

    async def _coverage_notes(self, reader: UsageReader, rng: DateRange) -> list[str]:
        present = await reader.days_with_data(rng.start, rng.end)
        if not present:
            return []
        gaps = missing_spans(rng.start, rng.end, present)
        if not gaps:
            return []
        shown = ", ".join(
            a.isoformat() if a == b else f"{a.isoformat()}..{b.isoformat()}" for a, b in gaps[:5]
        )
        more = f" (+{len(gaps) - 5} more)" if len(gaps) > 5 else ""
        return [f"Missing data for: {shown}{more}."]

    @staticmethod
    async def _check_known(reader: UsageReader, site_id: str | None, meter_id: str | None) -> None:
        """Reader is already customer-scoped, so another customer's ID looks exactly like an unknown one."""
        if not site_id and not meter_id:
            return
        known = await reader.sites_and_meters()
        if site_id and site_id not in {m.site_id for m in known}:
            raise InvalidArgument(f"Unknown site_id '{site_id}'. Use list_sites_and_meters.")
        if meter_id and meter_id not in {m.meter_id for m in known}:
            raise InvalidArgument(f"Unknown meter_id '{meter_id}'. Use list_sites_and_meters.")

    @staticmethod
    def _check_hourly(rng: DateRange, granularity: Granularity) -> None:
        if granularity == Granularity.HOUR and rng.days > MAX_HOURLY_DAYS:
            raise InvalidRange(f"Hourly data is limited to {MAX_HOURLY_DAYS} days; use day or month.")

    # ---- tools ----------------------------------------------------------------------------------
    async def get_usage(
        self,
        caller: Caller,
        start: str,
        end: str,
        granularity: Granularity,
        site_id: str | None = None,
        meter_id: str | None = None,
        channel: str = "rest",
    ) -> ToolResult:
        site_id, meter_id = _check_id("site_id", site_id), _check_id("meter_id", meter_id)
        params = {
            "start": start,
            "end": end,
            "granularity": granularity,
            "site_id": site_id,
            "meter_id": meter_id,
        }

        async def body(customer: CustomerContext, reader: UsageReader) -> ToolResult:
            rng, notes = self._range(start, end, customer.timezone)
            self._check_hourly(rng, granularity)
            await self._check_known(reader, site_id, meter_id)
            points = await reader.series(SeriesQuery(rng, granularity, site_id, meter_id))
            if not points:
                raise NoData(f"No usage data for {rng.label()}.")
            notes += await self._coverage_notes(reader, rng)
            if site_id or meter_id:
                notes.append(f"Filtered to {'site ' + site_id if site_id else 'meter ' + str(meter_id)}.")
            total = sum(p.kwh for p in points)
            return ToolResult(
                result_id=_new_result_id(),
                tool="get_usage",
                columns=[
                    Column(key="period", label="Period", type="string"),
                    Column(key="kwh", label="kWh", type="number"),
                ],
                rows=[{"period": _fmt_period(p.period, granularity), "kwh": _r(p.kwh)} for p in points],
                tz=customer.timezone,
                assumptions=notes,
                summary={
                    "total_kwh": _r(total),
                    "periods": len(points),
                    "start": rng.start.isoformat(),
                    "end": rng.end.isoformat(),
                    "granularity": str(granularity),
                },
                chart_hint=ChartHint(
                    type="bar" if len(points) <= 14 else "line",
                    x="period",
                    y=["kwh"],
                    title=f"Usage {rng.label()}",
                ),
            )

        return await self._run(caller, "get_usage", params, channel, body)

    async def compare_usage(
        self,
        caller: Caller,
        a_start: str,
        a_end: str,
        b_start: str,
        b_end: str,
        granularity: Granularity,
        channel: str = "rest",
    ) -> ToolResult:
        params = {"a": [a_start, a_end], "b": [b_start, b_end], "granularity": granularity}

        async def body(customer: CustomerContext, reader: UsageReader) -> ToolResult:
            tz = customer.timezone
            ra, na = self._range(a_start, a_end, tz)
            rb, nb = self._range(b_start, b_end, tz)
            notes = [f"Period A: {na[-1]}", f"Period B: {nb[-1]}"] + na[:-1] + nb[:-1]
            if ra.days != rb.days:
                if ra.partial != rb.partial:
                    days = min(ra.days, rb.days)
                    ra, rb = truncate(ra, days), truncate(rb, days)
                    notes.append(
                        f"Compared like-for-like: the first {days} day(s) of each period "
                        f"(A {ra.label()}, B {rb.label()})."
                    )
                else:
                    notes.append(f"Periods differ in length: A has {ra.days} days, B has {rb.days} days.")
            for r in (ra, rb):
                self._check_hourly(r, granularity)
            pa = await reader.series(SeriesQuery(ra, granularity))
            pb = await reader.series(SeriesQuery(rb, granularity))
            if not pa and not pb:
                raise NoData(f"No usage data for {ra.label()} or {rb.label()}.")
            notes += await self._coverage_notes(reader, ra) + await self._coverage_notes(reader, rb)
            ta, tb = sum(p.kwh for p in pa), sum(p.kwh for p in pb)
            by_a = {_offset(p.period, ra, granularity): p for p in pa}
            by_b = {_offset(p.period, rb, granularity): p for p in pb}
            rows = []
            for i in sorted(by_a.keys() | by_b.keys()):
                a: Point | None = by_a.get(i)
                b: Point | None = by_b.get(i)
                rows.append(
                    {
                        "step": i + 1,
                        "period_a": _fmt_period(a.period, granularity) if a else None,
                        "kwh_a": _r(a.kwh) if a else None,
                        "period_b": _fmt_period(b.period, granularity) if b else None,
                        "kwh_b": _r(b.kwh) if b else None,
                    }
                )
            pct = _r((ta - tb) / tb * 100) if tb else None
            return ToolResult(
                result_id=_new_result_id(),
                tool="compare_usage",
                columns=[
                    Column(key="step", label=f"{str(granularity).capitalize()} #", type="number"),
                    Column(key="period_a", label="Period A", type="string"),
                    Column(key="kwh_a", label="Period A kWh", type="number"),
                    Column(key="period_b", label="Period B", type="string"),
                    Column(key="kwh_b", label="Period B kWh", type="number"),
                ],
                rows=rows,
                tz=tz,
                assumptions=notes,
                summary={
                    "period_a": ra.label(),
                    "period_b": rb.label(),
                    "total_a_kwh": _r(ta),
                    "total_b_kwh": _r(tb),
                    "delta_kwh": _r(ta - tb),
                    "pct_change": pct,
                    "note": "delta = A - B; pct_change relative to B",
                },
                chart_hint=ChartHint(
                    type="line", x="step", y=["kwh_a", "kwh_b"], title="Period A vs Period B"
                ),
            )

        return await self._run(caller, "compare_usage", params, channel, body)

    async def get_peak_usage(
        self,
        caller: Caller,
        start: str,
        end: str,
        granularity: Granularity,
        top_n: int = 5,
        order: Order = Order.MAX,
        channel: str = "rest",
    ) -> ToolResult:
        if not 1 <= top_n <= MAX_TOP_N:
            raise InvalidArgument(f"top_n must be between 1 and {MAX_TOP_N}.")
        params = {"start": start, "end": end, "granularity": granularity, "top_n": top_n, "order": order}

        async def body(customer: CustomerContext, reader: UsageReader) -> ToolResult:
            rng, notes = self._range(start, end, customer.timezone)
            self._check_hourly(rng, granularity)
            points = await reader.series(SeriesQuery(rng, granularity))
            if not points:
                raise NoData(f"No usage data for {rng.label()}.")
            ranked = sorted(points, key=lambda p: p.kwh, reverse=order == Order.MAX)[:top_n]
            label = "Highest" if order == Order.MAX else "Lowest"
            notes.append(f"{label} {len(ranked)} {granularity} period(s) by kWh.")
            return ToolResult(
                result_id=_new_result_id(),
                tool="get_peak_usage",
                columns=[
                    Column(key="rank", label="Rank", type="number"),
                    Column(key="period", label="Period", type="string"),
                    Column(key="kwh", label="kWh", type="number"),
                ],
                rows=[
                    {"rank": i + 1, "period": _fmt_period(p.period, granularity), "kwh": _r(p.kwh)}
                    for i, p in enumerate(ranked)
                ],
                tz=customer.timezone,
                assumptions=notes,
                summary={
                    "order": str(order),
                    "top_n": top_n,
                    "start": rng.start.isoformat(),
                    "end": rng.end.isoformat(),
                },
                chart_hint=ChartHint(type="bar", x="period", y=["kwh"], title=f"{label} usage periods"),
            )

        return await self._run(caller, "get_peak_usage", params, channel, body)

    async def get_usage_breakdown(
        self,
        caller: Caller,
        start: str,
        end: str,
        group_by: GroupBy,
        granularity: BreakdownGranularity = BreakdownGranularity.TOTAL,
        channel: str = "rest",
    ) -> ToolResult:
        params = {"start": start, "end": end, "group_by": group_by, "granularity": granularity}

        async def body(customer: CustomerContext, reader: UsageReader) -> ToolResult:
            rng, notes = self._range(start, end, customer.timezone)
            groups = await reader.breakdown(rng, group_by, granularity)
            if not groups:
                raise NoData(f"No usage data for {rng.label()}.")
            notes += await self._coverage_notes(reader, rng)
            total = sum(g.kwh for g in groups)
            label = "Site" if group_by == GroupBy.SITE else "Meter"
            if granularity == BreakdownGranularity.TOTAL:
                rows = [
                    {
                        "group_id": g.group_id,
                        "group": g.group_name,
                        "kwh": _r(g.kwh),
                        "share_pct": _r(g.kwh / total * 100) if total else 0.0,
                    }
                    for g in sorted(groups, key=lambda g: g.kwh, reverse=True)
                ]
                columns = [
                    Column(key="group_id", label=f"{label} ID"),
                    Column(key="group", label=label),
                    Column(key="kwh", label="kWh", type="number"),
                    Column(key="share_pct", label="Share %", type="number"),
                ]
                hint = ChartHint(type="bar", x="group", y=["kwh"], title=f"Usage by {group_by}")
            else:
                rows = [
                    {
                        "period": _fmt_period(g.period, granularity) if g.period else None,
                        # Names can repeat (e.g. two "Main" meters); the ID keeps chart series distinct.
                        "group": f"{g.group_name} ({g.group_id})",
                        "kwh": _r(g.kwh),
                    }
                    for g in groups
                ]
                columns = [
                    Column(key="period", label="Period"),
                    Column(key="group", label=label),
                    Column(key="kwh", label="kWh", type="number"),
                ]
                hint = ChartHint(
                    type="line", x="period", y=["kwh"], series="group", title=f"Usage by {group_by}"
                )
            return ToolResult(
                result_id=_new_result_id(),
                tool="get_usage_breakdown",
                columns=columns,
                rows=rows,
                tz=customer.timezone,
                assumptions=notes,
                summary={"total_kwh": _r(total), "groups": len({g.group_id for g in groups})},
                chart_hint=hint,
            )

        return await self._run(caller, "get_usage_breakdown", params, channel, body)

    async def list_sites_and_meters(self, caller: Caller, channel: str = "rest") -> ToolResult:
        async def body(customer: CustomerContext, reader: UsageReader) -> ToolResult:
            meters = await reader.sites_and_meters()
            return ToolResult(
                result_id=_new_result_id(),
                tool="list_sites_and_meters",
                columns=[
                    Column(key="site_id", label="Site ID"),
                    Column(key="site", label="Site"),
                    Column(key="city", label="City"),
                    Column(key="meter_id", label="Meter ID"),
                    Column(key="meter", label="Meter"),
                    Column(key="type", label="Type"),
                ],
                rows=[
                    {
                        "site_id": m.site_id,
                        "site": m.site_name,
                        "city": m.city,
                        "meter_id": m.meter_id,
                        "meter": m.meter_name,
                        "type": m.meter_type,
                    }
                    for m in meters
                ],
                unit="",
                tz=customer.timezone,
                summary={"sites": len({m.site_id for m in meters}), "meters": len(meters)},
            )

        return await self._run(caller, "list_sites_and_meters", {}, channel, body)

    async def get_data_coverage(
        self, caller: Caller, start: str, end: str, channel: str = "rest"
    ) -> ToolResult:
        params = {"start": start, "end": end}

        async def body(customer: CustomerContext, reader: UsageReader) -> ToolResult:
            rng, notes = self._range(start, end, customer.timezone)
            present = await reader.days_with_data(rng.start, rng.end)
            gaps = missing_spans(rng.start, rng.end, present)
            return ToolResult(
                result_id=_new_result_id(),
                tool="get_data_coverage",
                columns=[
                    Column(key="from", label="Missing from", type="date"),
                    Column(key="to", label="Missing to", type="date"),
                    Column(key="days", label="Days", type="number"),
                ],
                rows=[
                    {"from": a.isoformat(), "to": b.isoformat(), "days": (b - a).days + 1} for a, b in gaps
                ],
                unit="days",
                tz=customer.timezone,
                assumptions=notes,
                summary={
                    "days_in_range": rng.days,
                    "days_with_data": len(present),
                    "coverage_pct": _r(len(present) / rng.days * 100),
                    "first_day_with_data": min(present).isoformat() if present else None,
                    "last_day_with_data": max(present).isoformat() if present else None,
                },
            )

        return await self._run(caller, "get_data_coverage", params, channel, body)
