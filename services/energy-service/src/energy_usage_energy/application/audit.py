"""BR-12 audit events. Never log prompts, model output, tokens or raw result rows."""

import logging
from typing import Any

_log = logging.getLogger("energy_usage.audit")


def audit_tool_call(
    *,
    tid: str,
    oid: str,
    customer_id: str | None,
    tool: str,
    params: dict[str, Any],
    row_count: int,
    latency_ms: float,
    outcome: str,
    channel: str,
) -> None:
    _log.info(
        "tool_call %s outcome=%s rows=%d latency_ms=%.1f",
        tool,
        outcome,
        row_count,
        latency_ms,
        extra={
            "event": "tool_call",
            "tid": tid,
            "oid": oid,
            "customer_id": customer_id,
            "tool": tool,
            "params": str(params),
            "row_count": row_count,
            "latency_ms": round(latency_ms, 1),
            "outcome": outcome,
            "channel": channel,
        },
    )
