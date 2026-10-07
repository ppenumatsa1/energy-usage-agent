from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from energy_usage_shared.problems import install_problem_handlers, problem_response

from ..application.errors import DataUnavailable, EnergyError

RETRY_AFTER_SECONDS = "5"


def install_error_handlers(app: FastAPI) -> None:
    install_problem_handlers(app)

    @app.exception_handler(EnergyError)
    async def _energy(_: Request, exc: EnergyError) -> JSONResponse:
        headers = {"Retry-After": RETRY_AFTER_SECONDS} if isinstance(exc, DataUnavailable) else None
        return problem_response(exc.status, exc.code, exc.title, exc.message, headers)
