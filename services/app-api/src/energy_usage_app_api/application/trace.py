"""'How this was answered': tool steps with timings plus the guardrails applied to the turn.
Holds tool names, arguments and counts only; result rows are in the response table."""

import time
from dataclasses import replace
from typing import Any, Literal

from ..projections.view import MAX_ROWS, View
from .models import ChatStatus, ToolCall, Trace, TraceCheck, TraceStep
from .ports import ToolGateway


class TimedGateway:
    """Wraps the per-turn gateway to time and record every call, whichever agent made it."""

    def __init__(self, inner: ToolGateway) -> None:
        self._inner = inner
        self.calls: list[ToolCall] = []

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolCall:
        start = time.perf_counter()
        call = await self._inner.call(name, arguments)
        call = replace(call, duration_ms=round((time.perf_counter() - start) * 1000))
        self.calls.append(call)
        return call


def build_trace(
    *,
    agent: Literal["fake", "foundry"],
    agent_name: str,
    duration_ms: int,
    status: ChatStatus,
    calls: list[ToolCall],
    view: View | None,
    result_ids: list[str] | None = None,
) -> Trace:
    steps = [
        TraceStep(
            tool=c.name,
            arguments=c.arguments,
            status="error" if c.error else "ok",
            rows=len(c.result.rows) if c.result else None,
            error_code=c.error.code if c.error else None,
            duration_ms=c.duration_ms,
            result_id=c.result.result_id if c.result else None,
            assumptions=c.result.assumptions if c.result else [],
            summary=c.result.summary if c.result else {},
            error_message=c.error.message if c.error else None,
        )
        for c in calls
    ]
    return Trace(
        agent=agent,
        agent_name=agent_name,
        duration_ms=duration_ms,
        steps=steps,
        checks=_checks(status, calls, view),
        result_ids=result_ids or [],
    )


def _checks(status: ChatStatus, calls: list[ToolCall], view: View | None) -> list[TraceCheck]:
    checks = [
        TraceCheck(
            name="Signed-in scope",
            detail="Data access used your sign-in; tools only see your own sites and meters.",
            outcome="pass",
        )
    ]
    if status == "refused":
        checks.append(
            TraceCheck(
                name="Energy topics only", detail="Question was outside energy usage.", outcome="blocked"
            )
        )
    else:
        checks.append(
            TraceCheck(name="Energy topics only", detail="Question is about energy usage.", outcome="pass")
        )
    if view and view.table:
        checks.append(
            TraceCheck(
                name="Numbers from tools",
                detail="Table and chart values come straight from tool results, not the model.",
                outcome="pass",
            )
        )
        if any(c.result and len(c.result.rows) > MAX_ROWS for c in calls):
            checks.append(
                TraceCheck(name="Row limit", detail=f"Table shows the first {MAX_ROWS} rows.", outcome="info")
            )
    errors = [c for c in calls if c.error]
    if errors:
        codes = ", ".join(sorted({c.error.code for c in errors if c.error}))
        checks.append(
            TraceCheck(
                name="Tool errors handled",
                detail=f"{len(errors)} tool call(s) returned {codes}; the answer reflects that.",
                outcome="info",
            )
        )
    return checks
