from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field

from ...application.models import Granularity
from ...application.service import UsageService
from ..server import caller_from, run_tool
from ._params import GranularityParam, Period


def register(mcp: FastMCP, service: UsageService) -> None:  # type: ignore[type-arg]
    @mcp.tool(
        name="compare_usage",
        description=(
            "Compare usage between two periods. period_a is the focus period, period_b the baseline; "
            "delta = A - B. Partial periods (e.g. month-to-date) are compared like-for-like."
        ),
    )
    async def compare_usage(
        ctx: Context,  # type: ignore[type-arg]
        period_a: Annotated[Period, Field(description="Focus period, e.g. this_month.")],
        period_b: Annotated[Period, Field(description="Baseline period, e.g. last_month.")],
        granularity: GranularityParam = "day",
    ) -> dict[str, Any]:
        return await run_tool(
            service.compare_usage(
                caller_from(ctx),
                period_a.start,
                period_a.end,
                period_b.start,
                period_b.end,
                Granularity(granularity),
                channel="mcp",
            )
        )
