from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field

from ...application.models import Granularity
from ...application.service import UsageService
from ..server import caller_from, run_tool
from ._params import End, GranularityParam, Start


def register(mcp: FastMCP, service: UsageService) -> None:  # type: ignore[type-arg]
    @mcp.tool(
        name="get_usage",
        description="Energy usage (kWh) over a period as a time series plus total, optionally for one site or meter.",
    )
    async def get_usage(
        ctx: Context,  # type: ignore[type-arg]
        start: Start,
        end: End,
        granularity: GranularityParam = "day",
        site_id: Annotated[
            str | None, Field(description="Optional site ID from list_sites_and_meters.")
        ] = None,
        meter_id: Annotated[
            str | None, Field(description="Optional meter ID from list_sites_and_meters.")
        ] = None,
    ) -> dict[str, Any]:
        return await run_tool(
            service.get_usage(
                caller_from(ctx), start, end, Granularity(granularity), site_id, meter_id, channel="mcp"
            )
        )
