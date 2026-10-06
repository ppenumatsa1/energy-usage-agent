"""RFC 7807 problem details shared by both services."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from .telemetry import get_correlation_id

PROBLEM_MEDIA_TYPE = "application/problem+json"
logger = logging.getLogger("energy_usage.problems")


class ProblemError(Exception):
    """An error that maps to an RFC 7807 response."""

    def __init__(
        self,
        status: int,
        code: str,
        title: str,
        detail: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail or title)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.headers = headers or {}


def problem_body(status: int, code: str, title: str, detail: str | None = None) -> dict[str, Any]:
    return {
        "type": f"https://errors.energy-usage.local/{code}",
        "title": title,
        "status": status,
        "detail": detail,
        "code": code,
        "correlationId": get_correlation_id(),
    }


def problem_response(
    status: int, code: str, title: str, detail: str | None = None, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        problem_body(status, code, title, detail),
        status_code=status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )


_HTTP_CODES = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}


def install_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def _problem(_: Request, exc: ProblemError) -> JSONResponse:
        headers = {**exc.headers, **({"WWW-Authenticate": "Bearer"} if exc.status == 401 else {})}
        return problem_response(exc.status, exc.code, exc.title, exc.detail, headers or None)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = sorted({".".join(str(p) for p in e.get("loc", ())[1:]) for e in exc.errors()})
        return problem_response(
            422, "invalid_request", "Invalid request", f"Invalid fields: {', '.join(fields)}"
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        return problem_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", extra={"event": "unhandled_error"})
        return problem_response(500, "internal_error", "Something went wrong")
