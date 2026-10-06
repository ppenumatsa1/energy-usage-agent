"""LOCAL ONLY (AUTH_MODE=dev): synthetic sign-in for the frontend. Never mounted in Azure."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from energy_usage_shared.auth import DEV_USERS, mint_dev_token
from energy_usage_shared.problems import ProblemError

from ..dependencies import get_container

router = APIRouter(prefix="/api/dev", tags=["dev"])


class DevTokenRequest(BaseModel):
    user: Literal["a1", "a2", "b1", "x1"]


@router.get("/users")
async def users() -> list[dict[str, str]]:
    return [{"id": u.id, "label": u.label} for u in DEV_USERS.values()]


@router.post("/token")
async def token(body: DevTokenRequest, request: Request) -> dict[str, str]:
    s = get_container(request).settings
    if s.auth_mode != "dev" or not s.dev_jwt_secret:
        raise ProblemError(404, "not_found", "Not found")
    u = DEV_USERS[body.user]
    return {
        "accessToken": mint_dev_token(
            s.dev_jwt_secret, s.auth_audience, s.auth_required_scope, u.tid, u.oid, u.name
        )
    }
