from typing import Annotated, Any, Literal

from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field

from ...application.models import BreakdownGranularity, GroupBy
from ...application.service import UsageService
from ..server import caller_from, run_tool
from ._params import End, Start


def register(mcp: FastMCP, service: UsageService) -> None:  # type: ignore[type-arg]
    @mcp.tool(
        name="get_usage_breakdown",
        description="Usage split by site or meter: totals with share %, or a per-period series per group.",
    )
    async def get_usage_breakdown(
        ctx: Context,  # type: ignore[type-arg]
        start: Start,
        end: End,
        group_by: Annotated[Literal["site", "meter"], Field(description="Group by site or meter.")] = "site",
        granularity: Annotated[
            Literal["total", "day", "month"], Field(description="total = one row per group.")
        ] = "total",
    ) -> dict[str, Any]:
        return await run_tool(
            service.get_usage_breakdown(
                caller_from(ctx),
                start,
                end,
                GroupBy(group_by),
                BreakdownGranularity(granularity),
                channel="mcp",
            )
        )
