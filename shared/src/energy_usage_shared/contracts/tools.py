from typing import Any, Literal

from pydantic import BaseModel, Field

TOOL_NAMES: tuple[str, ...] = (
    "get_usage",
    "compare_usage",
    "get_peak_usage",
    "get_usage_breakdown",
    "list_sites_and_meters",
    "get_data_coverage",
)


class Column(BaseModel):
    key: str
    label: str
    type: Literal["string", "number", "date"] = "string"


class ChartHint(BaseModel):
    type: Literal["line", "bar"]
    x: str
    y: list[str]
    series: str | None = None
    title: str = ""


class ToolResult(BaseModel):
    """Every tool and REST call returns this shape. Table/chart numbers come only from `rows`."""

    result_id: str
    tool: str
    columns: list[Column]
    rows: list[dict[str, Any]]
    unit: str = "kWh"
    tz: str
    assumptions: list[str] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    chart_hint: ChartHint | None = None


class ToolError(BaseModel):
    code: Literal["invalid_range", "invalid_argument", "no_data", "not_onboarded", "unauthorized", "internal"]
    message: str


def parse_tool_error(text: str) -> ToolError:
    """MCP servers may prefix the JSON payload (e.g. 'Error executing tool x: {...}')."""
    start = text.find("{")
    if start >= 0:
        try:
            return ToolError.model_validate_json(text[start:])
        except ValueError:
            pass
    return ToolError(code="internal", message="The tool failed. Try again.")
