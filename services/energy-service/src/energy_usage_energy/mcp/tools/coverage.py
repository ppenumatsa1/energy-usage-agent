from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ...application.service import UsageService
from ..server import caller_from, run_tool
from ._params import End, Start


def register(mcp: FastMCP, service: UsageService) -> None:  # type: ignore[type-arg]
    @mcp.tool(
        name="get_data_coverage", description="Which days have data in a period, and the missing spans."
    )
    async def get_data_coverage(ctx: Context, start: Start, end: End) -> dict[str, Any]:  # type: ignore[type-arg]
        return await run_tool(service.get_data_coverage(caller_from(ctx), start, end, channel="mcp"))
