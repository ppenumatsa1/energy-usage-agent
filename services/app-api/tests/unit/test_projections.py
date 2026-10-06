from energy_usage_app_api.application.models import ToolCall
from energy_usage_app_api.projections import project
from energy_usage_shared.contracts import AgentOutput, ChartHint, ChartSpec, Column, ToolError, ToolResult


def _result(rid: str, rows: list[dict], **kw) -> ToolResult:  # type: ignore[no-untyped-def,type-arg]
    return ToolResult(
        result_id=rid,
        tool="get_usage",
        columns=kw.pop(
            "columns", [Column(key="period", label="Period"), Column(key="kwh", label="kWh", type="number")]
        ),
        rows=rows,
        tz="UTC",
        **kw,
    )


ROWS = [{"period": "2026-01-01", "kwh": 1.0}, {"period": "2026-01-02", "kwh": 2.0}]


def test_numbers_come_from_tool_rows_not_the_model() -> None:
    r = _result("r_1", ROWS, assumptions=["a"])
    out = AgentOutput(
        answer="x", chart=ChartSpec(type="bar", x="period", y=["kwh"], title="t"), result_ids=["r_1"]
    )
    v = project(out, [ToolCall("get_usage", {}, result=r)])
    assert v.table and v.table["rows"] == ROWS
    assert v.chart == {"type": "bar", "x": "period", "y": ["kwh"], "title": "t"}
    assert v.assumptions == ["a"]


def test_primary_by_result_id_else_last() -> None:
    a, b = _result("r_a", ROWS), _result("r_b", ROWS[:1] * 3)
    calls = [ToolCall("get_usage", {}, result=a), ToolCall("get_usage", {}, result=b)]
    assert project(AgentOutput(answer="x", result_ids=["r_a"]), calls).table["rows"] == ROWS  # type: ignore[index]
    assert len(project(AgentOutput(answer="x", result_ids=["r_zzz"]), calls).table["rows"]) == 3  # type: ignore[index]


def test_invalid_chart_falls_back_to_hint() -> None:
    r = _result("r_1", ROWS, chart_hint=ChartHint(type="line", x="period", y=["kwh"], title="hint"))
    out = AgentOutput(answer="x", chart=ChartSpec(type="bar", x="nope", y=["made_up"]), result_ids=["r_1"])
    assert project(out, [ToolCall("get_usage", {}, result=r)]).chart["title"] == "hint"  # type: ignore[index]


def test_non_numeric_y_rejected() -> None:
    r = _result("r_1", ROWS)
    out = AgentOutput(answer="x", chart=ChartSpec(type="bar", x="kwh", y=["period"]), result_ids=["r_1"])
    assert project(out, [ToolCall("get_usage", {}, result=r)]).chart is None


def test_no_table_for_non_ok_status() -> None:
    r = _result("r_1", ROWS, assumptions=["note"])
    v = project(AgentOutput(answer="?", status="clarify"), [ToolCall("get_usage", {}, result=r)])
    assert v.table is None and v.chart is None and v.assumptions == ["note"]


def test_errors_only_gives_no_table() -> None:
    v = project(
        AgentOutput(answer="x"), [ToolCall("get_usage", {}, error=ToolError(code="no_data", message="m"))]
    )
    assert v.table is None


def test_long_rows_pivot_to_wide_series() -> None:
    cols = [
        Column(key="period", label="Period"),
        Column(key="group", label="Site"),
        Column(key="kwh", label="kWh", type="number"),
    ]
    rows = [
        {"period": "d1", "group": "A (S-1)", "kwh": 1.0},
        {"period": "d1", "group": "B (S-2)", "kwh": 2.0},
        {"period": "d2", "group": "A (S-1)", "kwh": 3.0},
    ]
    r = _result(
        "r_1", rows, columns=cols, chart_hint=ChartHint(type="line", x="period", y=["kwh"], series="group")
    )
    v = project(AgentOutput(answer="x", result_ids=["r_1"]), [ToolCall("b", {}, result=r)])
    assert v.table["rows"] == [
        {"period": "d1", "A (S-1)": 1.0, "B (S-2)": 2.0},
        {"period": "d2", "A (S-1)": 3.0},
    ]  # type: ignore[index]
    assert v.chart["y"] == ["A (S-1)", "B (S-2)"]  # type: ignore[index]


def test_single_row_has_table_but_no_chart() -> None:
    v = project(AgentOutput(answer="x"), [ToolCall("get_usage", {}, result=_result("r_1", ROWS[:1]))])
    assert v.table and v.chart is None
