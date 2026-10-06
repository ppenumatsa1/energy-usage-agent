from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ...application.service import UsageService
from ..server import caller_from, run_tool


def register(mcp: FastMCP, service: UsageService) -> None:  # type: ignore[type-arg]
    @mcp.tool(
        name="list_sites_and_meters", description="The signed-in customer's sites and meters with their IDs."
    )
    async def list_sites_and_meters(ctx: Context) -> dict[str, Any]:  # type: ignore[type-arg]
        return await run_tool(service.list_sites_and_meters(caller_from(ctx), channel="mcp"))
