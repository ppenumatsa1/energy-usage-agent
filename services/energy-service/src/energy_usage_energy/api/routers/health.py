import logging

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

router = APIRouter(tags=["health"])
_log = logging.getLogger("energy_usage.health")


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    try:
        ready = await request.app.state.container.repository.ping()
    except Exception:
        _log.warning("readiness_check_failed", exc_info=True, extra={"event": "readiness_check_failed"})
        ready = False
    if not ready:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ready"})
