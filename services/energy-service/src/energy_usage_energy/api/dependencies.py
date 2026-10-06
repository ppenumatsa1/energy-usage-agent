import logging

from fastapi import Request

from energy_usage_shared.auth import AuthError, bearer_token
from energy_usage_shared.problems import ProblemError

from ..application.models import Caller
from ..application.service import UsageService
from ..bootstrap import Container

_log = logging.getLogger("energy_usage.auth")


def get_container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]


def get_service(request: Request) -> UsageService:
    return get_container(request).service


def get_caller(request: Request) -> Caller:
    """Sync on purpose: FastAPI runs it in a thread, so a JWKS refresh never blocks the event loop."""
    container = get_container(request)
    try:
        principal = container.validator.validate(bearer_token(request.headers.get("authorization")))
    except AuthError as exc:
        _log.warning("authz_denied", extra={"event": "authz_denied", "reason": exc.reason, "channel": "rest"})
        raise ProblemError(
            401, "unauthorized", "Authentication required", "A valid access token is required."
        ) from exc
    return Caller(tid=principal.tid, oid=principal.oid)
