from typing import Annotated

from fastapi import APIRouter, Depends

from energy_usage_shared.contracts import Me

from ...application.models import Caller
from ...application.service import UsageService
from ..dependencies import get_caller, get_service

router = APIRouter(prefix="/v1", tags=["me"])


@router.get("/me", response_model=Me)
async def me(
    caller: Annotated[Caller, Depends(get_caller)], service: Annotated[UsageService, Depends(get_service)]
) -> Me:
    return await service.me(caller)
