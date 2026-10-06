import logging
from typing import Annotated

from fastapi import Depends, Request

from energy_usage_shared.auth import AuthError, Principal, bearer_token
from energy_usage_shared.problems import ProblemError
from energy_usage_shared.telemetry import get_correlation_id, new_correlation_id

from ..application.chat_service import ChatService
from ..bootstrap import Container

_log = logging.getLogger("energy_usage.auth")


def get_container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]


def get_chat(request: Request) -> ChatService:
    return get_container(request).chat


def get_principal(request: Request) -> Principal:
    """Sync on purpose: FastAPI runs it in a thread, so a JWKS refresh never blocks the event loop."""
    try:
        return get_container(request).validator.validate(bearer_token(request.headers.get("authorization")))
    except AuthError as exc:
        _log.warning(
            "authz_denied", extra={"event": "authz_denied", "reason": exc.reason, "channel": "app-api"}
        )
        raise ProblemError(401, "unauthorized", "Authentication required", "Sign in again.") from exc


def correlation_id() -> str:
    return get_correlation_id() or new_correlation_id()


PrincipalDep = Annotated[Principal, Depends(get_principal)]
ChatDep = Annotated[ChatService, Depends(get_chat)]
