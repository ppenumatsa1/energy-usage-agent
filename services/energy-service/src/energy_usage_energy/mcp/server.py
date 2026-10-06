import json
from collections.abc import Awaitable
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp

from energy_usage_shared.auth import TokenValidator
from energy_usage_shared.contracts import ToolResult

from ..application.errors import EnergyError
from ..application.models import Caller
from ..application.service import UsageService
from .auth import SCOPE_KEY, McpAuthMiddleware

INSTRUCTIONS = (
    "Energy usage tools for the signed-in customer. The customer is derived from the caller's token; "
    "tools never accept a customer identifier."
)


def caller_from(ctx: Context) -> Caller:  # type: ignore[type-arg]
    request = ctx.request_context.request
    caller = request.scope.get(SCOPE_KEY) if request is not None else None
    if not isinstance(caller, Caller):
        raise ToolError(json.dumps({"code": "unauthorized", "message": "Authentication required."}))
    return caller


async def run_tool(call: Awaitable[ToolResult]) -> dict[str, Any]:
    """Map application errors to MCP tool errors with a small JSON payload the agent can read."""
    try:
        result = await call
    except EnergyError as exc:
        raise ToolError(json.dumps({"code": exc.code, "message": exc.message})) from exc
    except Exception as exc:
        raise ToolError(json.dumps({"code": "internal", "message": "The tool failed. Try again."})) from exc
    return result.model_dump(mode="json")


def build_mcp(service: UsageService) -> FastMCP:  # type: ignore[type-arg]
    from .tools import breakdown, compare, coverage, meters, peaks, usage

    mcp = FastMCP(
        "energy-usage",
        instructions=INSTRUCTIONS,
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp",
        # Bearer auth is required on every request and no cookies are used, so DNS-rebinding
        # protection (meant for unauthenticated localhost servers) is not needed behind ACA ingress.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    for module in (usage, compare, peaks, breakdown, meters, coverage):
        module.register(mcp, service)
    return mcp


def build_mcp_app(service: UsageService, validator: TokenValidator) -> tuple[FastMCP, ASGIApp]:  # type: ignore[type-arg]
    mcp = build_mcp(service)
    return mcp, McpAuthMiddleware(mcp.streamable_http_app(), validator)
