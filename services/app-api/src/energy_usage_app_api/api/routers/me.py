from fastapi import APIRouter

from ...application.models import MeResponse, StatusResponse
from ..dependencies import ChatDep, PrincipalDep

router = APIRouter(prefix="/api", tags=["me"])


@router.get("/me", response_model=MeResponse, response_model_by_alias=True)
async def me(principal: PrincipalDep, service: ChatDep) -> MeResponse:
    return await service.me(principal)


@router.get("/status", response_model=StatusResponse, response_model_by_alias=True)
async def status(_principal: PrincipalDep, service: ChatDep) -> StatusResponse:
    """Component health for the signed-in UI (header pills). Public probes stay at /healthz."""
    return await service.status()
