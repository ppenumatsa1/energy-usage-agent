from typing import Annotated, Any, Literal

from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field

from ...application.models import Granularity, Order
from ...application.service import UsageService
from ..server import caller_from, run_tool
from ._params import End, GranularityParam, Start


def register(mcp: FastMCP, service: UsageService) -> None:  # type: ignore[type-arg]
    @mcp.tool(name="get_peak_usage", description="Highest (max) or lowest (min) usage periods, ranked.")
    async def get_peak_usage(
        ctx: Context,  # type: ignore[type-arg]
        start: Start,
        end: End,
        granularity: GranularityParam = "day",
        top_n: Annotated[int, Field(ge=1, le=10, description="How many periods to return (1-10).")] = 5,
        order: Annotated[Literal["max", "min"], Field(description="max = highest, min = lowest.")] = "max",
    ) -> dict[str, Any]:
        return await run_tool(
            service.get_peak_usage(
                caller_from(ctx), start, end, Granularity(granularity), top_n, Order(order), channel="mcp"
            )
        )
