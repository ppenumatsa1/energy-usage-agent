from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

DATE_HELP = (
    "Local date (customer time zone): YYYY-MM-DD, YYYY-MM, or a server-resolved keyword: today, yesterday, "
    "this_week, last_week, this_month, last_month, this_year, last_year, last_7_days, last_30_days, "
    "last_90_days, last_12_months. A keyword as start means the period start; as end, the period end."
)

Start = Annotated[str, Field(description="Period start. " + DATE_HELP, max_length=20)]
End = Annotated[str, Field(description="Period end, inclusive. Same formats as start.", max_length=20)]
GranularityParam = Annotated[
    Literal["hour", "day", "month"],
    Field(description="Bucket size. hour is allowed for ranges up to 31 days."),
]


class Period(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: Start
    end: End
