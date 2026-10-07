import json
import logging
from collections.abc import Awaitable, Sequence
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ContentBlock
from pydantic import ValidationError
from starlette.types import ASGIApp

from energy_usage_shared.auth import TokenValidator
from energy_usage_shared.contracts import ToolResult
from energy_usage_shared.telemetry import CORRELATION_SCOPE_KEY, get_correlation_id, set_correlation_id

from ..application.errors import EnergyError
from ..application.models import Caller
from ..application.service import UsageService
from .auth import SCOPE_KEY, McpAuthMiddleware

_log = logging.getLogger("energy_usage.mcp")
GENERIC_FAILURE = "The tool failed. Try again."

INSTRUCTIONS = (
    "Energy usage tools for the signed-in customer. The customer is derived from the caller's token; "
    "tools never accept a customer identifier."
)


def _log_extra(tool: str | None = None) -> dict[str, Any]:
    return {"event": "tool_unhandled_error", "tool": tool, "correlation_id": get_correlation_id() or "-"}


def tool_error(code: str, message: str) -> ToolError:
    """The text payload app-api parses with shared.contracts.parse_tool_error."""
    return ToolError(json.dumps({"code": code, "message": message}))


def caller_from(ctx: Context) -> Caller:  # type: ignore[type-arg]
    request = ctx.request_context.request
    # Context vars don't survive into the MCP task group; restore the request's correlation ID for logs.
    if request is not None and get_correlation_id() is None:
        set_correlation_id(request.scope.get(CORRELATION_SCOPE_KEY))
    caller = request.scope.get(SCOPE_KEY) if request is not None else None
    if not isinstance(caller, Caller):
        raise tool_error("unauthorized", "Authentication required.")
    return caller


async def run_tool(call: Awaitable[ToolResult]) -> dict[str, Any]:
    """Map application errors to MCP tool errors with a small JSON payload the agent can read."""
    try:
        result = await call
    except EnergyError as exc:
        raise tool_error(exc.mcp_code, exc.message) from exc
    except Exception as exc:
        _log.exception("tool_unhandled_error", extra=_log_extra())
        raise tool_error("internal", GENERIC_FAILURE) from exc
    return result.model_dump(mode="json")


class EnergyMCP(FastMCP):  # type: ignore[type-arg]
    """FastMCP that keeps every tool failure in the ToolError JSON format: argument validation errors
    become invalid_argument (field names only, no input echo) and anything unexpected becomes a
    generic internal error that is logged, never raw exception text."""

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> Sequence[ContentBlock] | dict[str, Any]:
        try:
            return await super().call_tool(name, arguments)
        except ToolError as exc:
            cause = exc.__cause__
            if isinstance(cause, ValidationError):
                fields = sorted({".".join(str(p) for p in e["loc"]) or "arguments" for e in cause.errors()})
                raise tool_error("invalid_argument", f"Invalid arguments: {', '.join(fields)}.") from cause
            if cause is None or isinstance(cause, ToolError):
                raise  # already a deliberate, safe message (ours, or FastMCP's "Unknown tool")
            _log.error("tool_unhandled_error", exc_info=cause, extra=_log_extra(name))
            raise tool_error("internal", GENERIC_FAILURE) from cause
        except Exception as exc:
            _log.exception("tool_unhandled_error", extra=_log_extra(name))
            raise tool_error("internal", GENERIC_FAILURE) from exc


def build_mcp(service: UsageService) -> FastMCP:  # type: ignore[type-arg]
    from .tools import breakdown, compare, coverage, meters, peaks, usage

    mcp = EnergyMCP(
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
