"""MCP client to the energy-service, opened per chat turn with the user's OBO token (lazy connect)."""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from energy_usage_shared.contracts import TOOL_NAMES, ToolError, ToolResult, parse_tool_error
from energy_usage_shared.telemetry import CORRELATION_HEADER

from ..application.errors import UpstreamUnavailable
from ..application.models import ToolCall

_log = logging.getLogger("energy_usage.mcp_client")


class McpToolGateway:
    def __init__(self, url: str, headers: dict[str, str], stack: AsyncExitStack) -> None:
        self._url, self._headers, self._stack = url, headers, stack
        self._session: ClientSession | None = None

    async def _connect(self) -> ClientSession:
        if self._session is None:
            try:
                http = await self._stack.enter_async_context(
                    httpx.AsyncClient(headers=self._headers, timeout=httpx.Timeout(30, read=60))
                )
                read, write, _ = await self._stack.enter_async_context(
                    streamable_http_client(self._url, http_client=http)
                )
                session = await self._stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
            except Exception as exc:
                raise UpstreamUnavailable("The energy service is unavailable.") from exc
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
            raise UpstreamUnavailable("The energy service is unavailable.") from exc
        if res.isError:
            text = res.content[0].text if res.content and hasattr(res.content[0], "text") else ""
            return ToolCall(name, arguments, error=parse_tool_error(text))
        data = res.structuredContent
        if data is None and res.content and hasattr(res.content[0], "text"):
            data = json.loads(res.content[0].text)
        return ToolCall(name, arguments, result=ToolResult.model_validate(data))


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
