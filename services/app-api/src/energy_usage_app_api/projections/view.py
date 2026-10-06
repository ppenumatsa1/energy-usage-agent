from dataclasses import dataclass, field
from typing import Any

from energy_usage_shared.contracts import AgentOutput, ChartSpec, ToolResult

from ..application.models import ToolCall

MAX_ROWS = 500


@dataclass
class View:
    table: dict[str, Any] | None = None
    chart: dict[str, Any] | None = None
    assumptions: list[str] = field(default_factory=list)


def project(output: AgentOutput, calls: list[ToolCall]) -> View:
    """Pick the primary result and build table/chart from its rows. The LLM only chooses *which* result
    and *how* to plot it; every number shown comes from captured tool output."""
    results = [c.result for c in calls if c.result is not None]
    assumptions = _unique(a for r in results for a in r.assumptions)
    if output.status != "ok" or not results:
        return View(assumptions=assumptions)
    primary = _primary(output.result_ids, results)
    columns = [c.model_dump() for c in primary.columns]
    rows = primary.rows[:MAX_ROWS]
    chart_spec = _valid_chart(output.chart, primary) or _hint_chart(primary)
    if chart_spec and chart_spec.series:
        columns, rows, chart_spec = _pivot(primary, rows, chart_spec)
    table = {"columns": columns, "rows": rows, "unit": primary.unit}
    chart = (
        {"type": chart_spec.type, "x": chart_spec.x, "y": chart_spec.y, "title": chart_spec.title}
        if chart_spec and len(rows) > 1
        else None
    )
    return View(table=table, chart=chart, assumptions=assumptions)


def _primary(result_ids: list[str], results: list[ToolResult]) -> ToolResult:
    by_id = {r.result_id: r for r in results}
    for rid in result_ids:
        if rid in by_id:
            return by_id[rid]
    return results[-1]


def _valid_chart(spec: ChartSpec | None, result: ToolResult) -> ChartSpec | None:
    if spec is None:
        return None
    keys = {c.key for c in result.columns}
    numeric = {c.key for c in result.columns if c.type == "number"}
    if spec.x not in keys or not spec.y or not set(spec.y) <= numeric:
        return None
    if spec.series and spec.series not in keys:
        return None
    return spec


def _hint_chart(result: ToolResult) -> ChartSpec | None:
    h = result.chart_hint
    if h is None:
        return None
    return _valid_chart(ChartSpec(type=h.type, x=h.x, y=h.y, series=h.series, title=h.title), result)


def _pivot(
    result: ToolResult, rows: list[dict[str, Any]], spec: ChartSpec
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], ChartSpec]:
    """Long rows (x, series, value) -> wide rows (x, series_1, series_2, ...)."""
    value = spec.y[0]
    groups: list[str] = []
    wide: dict[Any, dict[str, Any]] = {}
    for row in rows:
        g = str(row.get(spec.series or ""))
        if g not in groups:
            groups.append(g)
        x = row.get(spec.x)
        wide.setdefault(x, {spec.x: x})[g] = row.get(value)
    x_col = next(c for c in result.columns if c.key == spec.x)
    columns = [x_col.model_dump()] + [{"key": g, "label": g, "type": "number"} for g in groups]
    return columns, list(wide.values()), ChartSpec(type=spec.type, x=spec.x, y=groups, title=spec.title)


def _unique(items: Any) -> list[str]:
    seen: list[str] = []
    for i in items:
        if i not in seen:
            seen.append(i)
    return seen
