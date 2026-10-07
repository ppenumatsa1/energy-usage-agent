"""MCP client to the energy-service, opened per chat turn with the user's OBO token (lazy connect)."""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import timedelta
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import ValidationError

from energy_usage_shared.contracts import TOOL_NAMES, ToolError, ToolResult, parse_tool_error
from energy_usage_shared.telemetry import CORRELATION_HEADER

from ..application.errors import UpstreamUnavailable
from ..application.models import ToolCall

_log = logging.getLogger("energy_usage.mcp_client")
MCP_TIMEOUT = httpx.Timeout(30, read=60)
MCP_REQUEST_TIMEOUT = timedelta(seconds=60)  # whole MCP request (initialize, tools/call)
UNEXPECTED_RESULT = ToolError(code="internal", message="The energy service returned an unexpected result.")


def _unavailable(event: str, name: str | None, exc: BaseException) -> UpstreamUnavailable:
    _log.warning(event, extra={"event": event, "tool": name, "error": type(exc).__name__})
    return UpstreamUnavailable("The energy service is unavailable. Try again in a moment.")


class McpToolGateway:
    def __init__(self, url: str, headers: dict[str, str], stack: AsyncExitStack) -> None:
        self._url, self._headers, self._stack = url, headers, stack
        self._session: ClientSession | None = None

    async def _connect(self) -> ClientSession:
        if self._session is None:
            try:
                http = await self._stack.enter_async_context(
                    httpx.AsyncClient(headers=self._headers, timeout=MCP_TIMEOUT)
                )
                read, write, _ = await self._stack.enter_async_context(
                    streamable_http_client(self._url, http_client=http)
                )
                session = await self._stack.enter_async_context(
                    ClientSession(read, write, read_timeout_seconds=MCP_REQUEST_TIMEOUT)
                )
                await session.initialize()
            except Exception as exc:
                raise _unavailable("mcp_connect_failed", None, exc) from exc
            self._session = session
        return self._session

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolCall:
        if name not in TOOL_NAMES:  # allow-list: the model cannot reach anything else
            return ToolCall(
                name, arguments, error=ToolError(code="invalid_argument", message=f"Unknown tool {name}.")
            )
        session = await self._connect()
        try:
            res = await session.call_tool(name, arguments)
        except Exception as exc:
            raise _unavailable("mcp_call_failed", name, exc) from exc
        if res.isError:
            text = res.content[0].text if res.content and hasattr(res.content[0], "text") else ""
            return ToolCall(name, arguments, error=parse_tool_error(text))
        try:
            data = res.structuredContent
            if data is None and res.content and hasattr(res.content[0], "text"):
                data = json.loads(res.content[0].text)
            if data is None:
                raise ValueError("no content")
            result = ToolResult.model_validate(data)
        except (ValueError, ValidationError) as exc:
            # The model gets a tool error it can explain; the payload is never logged (customer data).
            _log.warning(
                "mcp_result_invalid",
                extra={"event": "mcp_result_invalid", "tool": name, "error": type(exc).__name__},
            )
            return ToolCall(name, arguments, error=UNEXPECTED_RESULT)
        return ToolCall(name, arguments, result=result)


class McpToolGatewayFactory:
    def __init__(self, base_url: str) -> None:
        self._url = base_url.rstrip("/") + "/mcp"

    @asynccontextmanager
    async def open(self, user_token: str, correlation_id: str) -> AsyncIterator[McpToolGateway]:
        headers = {"Authorization": f"Bearer {user_token}", CORRELATION_HEADER: correlation_id}
        try:
            async with AsyncExitStack() as stack:
                yield McpToolGateway(self._url, headers, stack)
        except BaseExceptionGroup as group:
            # The MCP client's task group wraps errors raised in the turn; re-raise the first real one
            # so app errors (e.g. UpstreamUnavailable) keep their status code.
            leaf: BaseException = group
            while isinstance(leaf, BaseExceptionGroup):
                leaf = leaf.exceptions[0]
            raise leaf from None
