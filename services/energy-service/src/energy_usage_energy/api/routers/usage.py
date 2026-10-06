from typing import Annotated

from fastapi import APIRouter, Depends, Query

from energy_usage_shared.contracts import ToolResult

from ...application.models import BreakdownGranularity, Caller, Granularity, GroupBy, Order
from ...application.service import UsageService
from ..dependencies import get_caller, get_service

router = APIRouter(prefix="/v1/usage", tags=["usage"])
CallerDep = Annotated[Caller, Depends(get_caller)]
ServiceDep = Annotated[UsageService, Depends(get_service)]
DateParam = Annotated[
    str, Query(max_length=20, description="YYYY-MM-DD, YYYY-MM or a keyword like this_month")
]


@router.get("", response_model=ToolResult)
async def get_usage(
    caller: CallerDep,
    service: ServiceDep,
    start: DateParam,
    end: DateParam,
    granularity: Granularity = Granularity.DAY,
    site_id: Annotated[str | None, Query(max_length=64)] = None,
    meter_id: Annotated[str | None, Query(max_length=64)] = None,
) -> ToolResult:
    return await service.get_usage(caller, start, end, granularity, site_id, meter_id)


@router.get("/compare", response_model=ToolResult)
async def compare_usage(
    caller: CallerDep,
    service: ServiceDep,
    a_start: DateParam,
    a_end: DateParam,
    b_start: DateParam,
    b_end: DateParam,
    granularity: Granularity = Granularity.DAY,
) -> ToolResult:
    return await service.compare_usage(caller, a_start, a_end, b_start, b_end, granularity)


@router.get("/peaks", response_model=ToolResult)
async def get_peaks(
    caller: CallerDep,
    service: ServiceDep,
    start: DateParam,
    end: DateParam,
    granularity: Granularity = Granularity.DAY,
    top_n: Annotated[int, Query(ge=1, le=10)] = 5,
    order: Order = Order.MAX,
) -> ToolResult:
    return await service.get_peak_usage(caller, start, end, granularity, top_n, order)


@router.get("/breakdown", response_model=ToolResult)
async def get_breakdown(
    caller: CallerDep,
    service: ServiceDep,
    start: DateParam,
    end: DateParam,
    group_by: GroupBy = GroupBy.SITE,
    granularity: BreakdownGranularity = BreakdownGranularity.TOTAL,
) -> ToolResult:
    return await service.get_usage_breakdown(caller, start, end, group_by, granularity)
