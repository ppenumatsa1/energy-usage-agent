from typing import Annotated

from fastapi import APIRouter, Depends, Query

from energy_usage_shared.contracts import ToolResult

from ...application.models import Caller
from ...application.service import UsageService
from ..dependencies import get_caller, get_service

router = APIRouter(prefix="/v1", tags=["coverage"])


@router.get("/coverage", response_model=ToolResult)
async def get_coverage(
    caller: Annotated[Caller, Depends(get_caller)],
    service: Annotated[UsageService, Depends(get_service)],
    start: Annotated[str, Query(max_length=20)],
    end: Annotated[str, Query(max_length=20)],
) -> ToolResult:
    return await service.get_data_coverage(caller, start, end)
