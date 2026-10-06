"""Bearer-token gate for /mcp. The validated caller is stored in the ASGI scope, which FastMCP exposes
to tools as ctx.request_context.request (context vars do not survive into the MCP task group)."""

import json
import logging

import anyio
from starlette.types import ASGIApp, Receive, Scope, Send

from energy_usage_shared.auth import AuthError, TokenValidator, bearer_token
from energy_usage_shared.problems import PROBLEM_MEDIA_TYPE, problem_body

from ..application.models import Caller

SCOPE_KEY = "energy_usage.caller"
_log = logging.getLogger("energy_usage.auth")


class McpAuthMiddleware:
    def __init__(self, app: ASGIApp, validator: TokenValidator) -> None:
        self.app = app
        self.validator = validator

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        try:
            token = bearer_token(headers.get("authorization"))
            principal = await anyio.to_thread.run_sync(self.validator.validate, token)
        except AuthError as exc:
            _log.warning(
                "authz_denied", extra={"event": "authz_denied", "reason": exc.reason, "channel": "mcp"}
            )
            body = json.dumps(problem_body(401, "unauthorized", "Authentication required")).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", PROBLEM_MEDIA_TYPE.encode()),
                        (b"www-authenticate", b"Bearer"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        scope[SCOPE_KEY] = Caller(tid=principal.tid, oid=principal.oid)
        await self.app(scope, receive, send)
