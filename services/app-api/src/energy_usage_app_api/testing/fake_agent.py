"""LOCAL/TEST ONLY: a deterministic keyword 'agent' that calls the real tools, so the full stack runs
without Foundry. It is not a model and makes no attempt to understand language."""

import re
import uuid
from typing import Any

from energy_usage_shared.contracts import AgentOutput, ChartSpec

from ..application.models import AgentTurn, Emit, ToolCall
from ..application.ports import ToolGateway

_REFUSE = re.compile(r"\b(cost|price|tariff|bill|invoice|\$)", re.I)


def _plan(message: str) -> tuple[str, dict[str, Any]] | None:
    m = message.lower()
    if _REFUSE.search(m):
        return None
    if "compare" in m or " vs" in m or "versus" in m:
        return "compare_usage", {
            "period_a": {"start": "this_month", "end": "this_month"},
            "period_b": {"start": "last_month", "end": "last_month"},
            "granularity": "day",
        }
    if "peak" in m or "highest" in m or "lowest" in m:
        return "get_peak_usage", {
            "start": "last_30_days", "end": "last_30_days", "granularity": "day", "top_n": 5,
            "order": "min" if "lowest" in m else "max",
        }  # fmt: skip
    if "site" in m and ("by" in m or "breakdown" in m or "split" in m):
        return "get_usage_breakdown", {"start": "last_month", "end": "last_month", "group_by": "site"}
    if "meter" in m and ("list" in m or "which" in m or "what" in m):
        return "list_sites_and_meters", {}
    if "missing" in m or "coverage" in m or "gap" in m:
        return "get_data_coverage", {"start": "last_30_days", "end": "last_30_days"}
    if "today" in m or "hour" in m:
        return "get_usage", {"start": "today", "end": "today", "granularity": "hour"}
    if "year" in m or "monthly" in m:
        return "get_usage", {"start": "last_12_months", "end": "last_12_months", "granularity": "month"}
    if "last month" in m:
        return "get_usage", {"start": "last_month", "end": "last_month", "granularity": "day"}
    return "get_usage", {"start": "last_30_days", "end": "last_30_days", "granularity": "day"}


def _answer(call: ToolCall) -> AgentOutput:
    if call.error:
        status = "no_data" if call.error.code == "no_data" else "clarify"
        return AgentOutput(answer=call.error.message, status=status)
    r = call.result
    assert r is not None
    s = r.summary
    if "total_kwh" in s:
        text = f"Total usage was {s['total_kwh']:,} kWh over {s.get('periods', len(r.rows))} period(s)."
    elif "delta_kwh" in s:
        text = (
            f"Period A used {s['total_a_kwh']:,} kWh vs {s['total_b_kwh']:,} kWh ({s['delta_kwh']:+,} kWh)."
        )
    elif "coverage_pct" in s:
        text = f"Data covers {s['coverage_pct']}% of days in the range."
    else:
        text = f"Here are {len(r.rows)} row(s)."
    chart = None
    if r.chart_hint:
        h = r.chart_hint
        chart = ChartSpec(type=h.type, x=h.x, y=h.y, series=h.series, title=h.title)
    return AgentOutput(answer=f"[fake agent] {text}", status="ok", chart=chart, result_ids=[r.result_id])


class FakeAgentRunner:
    async def run_turn(
        self, message: str, agent_conversation_id: str | None, tools: ToolGateway, emit: Emit
    ) -> AgentTurn:
        conv = agent_conversation_id or f"fake_{uuid.uuid4().hex}"
        plan = _plan(message)
        if plan is None:
            out = AgentOutput(
                answer="I can only answer questions about energy usage, not costs or billing.",
                status="refused",
            )
            return AgentTurn(out, conv)
        name, args = plan
        await emit("status", {"stage": "tool", "tool": name})
        call = await tools.call(name, args)
        return AgentTurn(_answer(call), conv, [call])

    async def forget(self, agent_conversation_id: str) -> None:
        return None
