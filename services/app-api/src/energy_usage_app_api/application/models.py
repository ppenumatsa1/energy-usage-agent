from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from energy_usage_shared.contracts import AgentOutput, Column, ToolError, ToolResult

ChatStatus = Literal["ok", "no_data", "clarify", "refused", "error"]
Stage = Literal["thinking", "tool", "composing"]
# emit(event, data): progress events for streaming clients (no-op for JSON clients).
Emit = Callable[[str, dict[str, Any]], Awaitable[None]]


async def no_emit(_event: str, _data: dict[str, Any]) -> None:
    return None


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ChatRequest(ApiModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: UUID | None = None


class TableData(ApiModel):
    columns: list[Column]
    rows: list[dict[str, Any]]
    unit: str


class ChartData(ApiModel):
    type: Literal["line", "bar"]
    x: str
    y: list[str]
    title: str


class TraceStep(ApiModel):
    """One tool call: name, arguments and outcome. Rows themselves are only in `table`."""

    tool: str
    arguments: dict[str, Any]
    status: Literal["ok", "error"]
    rows: int | None = None
    error_code: str | None = None
    duration_ms: int
    result_id: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None


class TraceCheck(ApiModel):
    name: str
    detail: str
    outcome: Literal["pass", "info", "blocked"]


class Trace(ApiModel):
    """'How this was answered': shown to the user next to each answer."""

    agent: Literal["fake", "foundry"]
    agent_name: str
    duration_ms: int
    steps: list[TraceStep] = Field(default_factory=list)
    checks: list[TraceCheck] = Field(default_factory=list)
    result_ids: list[str] = Field(default_factory=list)  # tool results the agent based its answer on


class ChatResponse(ApiModel):
    answer: str
    status: ChatStatus
    table: TableData | None = None
    chart: ChartData | None = None
    assumptions: list[str] = Field(default_factory=list)
    conversation_id: UUID
    correlation_id: str
    created_at: datetime
    trace: Trace


class MeResponse(ApiModel):
    onboarded: bool
    customer_name: str | None = None
    timezone: str | None = None
    user_name: str | None = None


class ConversationSummary(ApiModel):
    conversation_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    turn_count: int


class ConversationTurn(ApiModel):
    question: str
    response: ChatResponse


class ConversationDetail(ApiModel):
    conversation_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    turns: list[ConversationTurn]


class StatusComponent(ApiModel):
    id: Literal["api", "energy", "database", "agent"]
    label: str
    status: Literal["ok", "down"]
    detail: str


class StatusResponse(ApiModel):
    components: list[StatusComponent]
    history_retention_days: int


@dataclass(frozen=True)
class ConversationRecord:
    conversation_id: UUID
    tid: str
    oid: str
    agent_conversation_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    turn_count: int = 0


@dataclass(frozen=True)
class StoredTurn:
    question: str
    response: dict[str, Any]  # ChatResponse JSON (by alias), exactly what the user saw


@dataclass(frozen=True)
class ToolCall:
    """One tool call made during a turn. Exactly one of result / error is set."""

    name: str
    arguments: dict[str, Any]
    result: ToolResult | None = None
    error: ToolError | None = None
    duration_ms: int = 0


@dataclass
class AgentTurn:
    output: AgentOutput
    agent_conversation_id: str
    calls: list[ToolCall] = field(default_factory=list)
