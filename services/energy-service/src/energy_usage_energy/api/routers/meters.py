from typing import Annotated

from fastapi import APIRouter, Depends

from energy_usage_shared.contracts import ToolResult

from ...application.models import Caller
from ...application.service import UsageService
from ..dependencies import get_caller, get_service

router = APIRouter(prefix="/v1", tags=["meters"])


@router.get("/sites", response_model=ToolResult)
async def list_sites(
    caller: Annotated[Caller, Depends(get_caller)], service: Annotated[UsageService, Depends(get_service)]
) -> ToolResult:
    return await service.list_sites_and_meters(caller)
