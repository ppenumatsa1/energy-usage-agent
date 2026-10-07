"""Logging, correlation IDs and optional Azure Monitor (App Insights) export."""

import logging
import os
import re
import uuid
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any

from fastapi.telemetry import TelemetryConfig
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CORRELATION_HEADER = "x-correlation-id"
# Also kept in the ASGI scope: code that runs outside the request's context (the outermost error
# handler, MCP tool task groups) can still read it.
CORRELATION_SCOPE_KEY = "energy_usage.correlation_id"
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_SAFE_ID = re.compile(r"^[A-Za-z0-9\-]{8,64}$")
_configured = False

# Standard OpenTelemetry settings, applied only when the environment doesn't set them.
TELEMETRY_ENV_DEFAULTS = {
    # Keep every trace. The distro's default is a 5 spans/s rate limit, which drops parts of chat turns.
    "OTEL_TRACES_SAMPLER": "microsoft.fixed_percentage",
    "OTEL_TRACES_SAMPLER_ARG": "1.0",
}

# Container Apps probes hit these every few seconds; tracing them is pure noise.
UNTRACED_PATHS = frozenset({"/healthz"})


def _untraced(scope: MutableMapping[str, Any]) -> bool:
    return scope.get("path") in UNTRACED_PATHS


# FastAPI traces requests natively; pass as `FastAPI(telemetry=FASTAPI_TELEMETRY)`.
FASTAPI_TELEMETRY: TelemetryConfig = {"exclude": _untraced}


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def set_correlation_id(value: str | None) -> None:
    _correlation_id.set(value)


def new_correlation_id() -> str:
    return uuid.uuid4().hex


class _CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "correlation_id"):
            record.correlation_id = get_correlation_id() or "-"
        return True


def configure_telemetry(service_name: str, connection_string: str | None, level: str = "INFO") -> None:
    """Configure logging once per process. Exports to App Insights when a connection string is set."""
    global _configured
    if _configured:
        return
    _configured = True
    handler = logging.StreamHandler()
    handler.addFilter(_CorrelationFilter())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(correlation_id)s] %(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # Azure SDK HTTP logging (incl. the App Insights exporter's own calls) floods the console at INFO.
    logging.getLogger("azure").setLevel(logging.WARNING)
    if connection_string:
        os.environ.setdefault("OTEL_SERVICE_NAME", service_name)
        for name, value in TELEMETRY_ENV_DEFAULTS.items():
            os.environ.setdefault(name, value)
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(
            connection_string=connection_string,
            logger_name="energy_usage",
            # FastAPI's native tracing covers requests; the contrib instrumentor would only duplicate it.
            instrumentation_options={"fastapi": {"enabled": False}},
        )
        for log_filter in (_CorrelationFilter(),):
            logging.getLogger("energy_usage").addFilter(log_filter)


class CorrelationIdMiddleware:
    """Pure ASGI middleware: accept a safe inbound correlation ID or create one; echo it back."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        inbound = None
        for name, value in scope.get("headers", []):
            if name.decode("latin-1").lower() == CORRELATION_HEADER:
                inbound = value.decode("latin-1")
                break
        cid = inbound if inbound and _SAFE_ID.match(inbound) else new_correlation_id()
        token = _correlation_id.set(cid)
        scope[CORRELATION_SCOPE_KEY] = cid

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((CORRELATION_HEADER.encode(), cid.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            _correlation_id.reset(token)
