from typing import Literal

from pydantic import BaseModel, Field

AnswerStatus = Literal["ok", "no_data", "clarify", "refused"]


class ChartSpec(BaseModel):
    type: Literal["line", "bar"]
    x: str
    y: list[str] = Field(min_length=1)
    series: str | None = None
    title: str = ""


class AgentOutput(BaseModel):
    """Structured output of the Foundry prompt agent (see agent/output-schema.json)."""

    answer: str
    status: AnswerStatus = "ok"
    chart: ChartSpec | None = None
    result_ids: list[str] = Field(default_factory=list)
