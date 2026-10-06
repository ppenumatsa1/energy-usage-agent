from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from energy_usage_shared.problems import install_problem_handlers, problem_response
from energy_usage_shared.telemetry import FASTAPI_TELEMETRY, CorrelationIdMiddleware

from ..application.errors import ChatError
from ..bootstrap import Container
from .routers import chat, conversations, dev, health, me


def create_app(container: Container) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        for start in container.startup:
            await start()
        try:
            yield
        finally:
            for stop in reversed(container.shutdown):
                await stop()

    app = FastAPI(title="app-api", version="0.1.0", lifespan=lifespan, telemetry=FASTAPI_TELEMETRY)
    app.state.container = container
    install_problem_handlers(app)

    @app.exception_handler(ChatError)
    async def _chat_error(_: Request, exc: ChatError) -> JSONResponse:
        return problem_response(exc.status, exc.code, exc.title, exc.detail, exc.headers or None)

    for r in (health.router, me.router, chat.router, conversations.router):
        app.include_router(r)
    if container.settings.auth_mode == "dev":
        app.include_router(dev.router)
    app.add_middleware(CorrelationIdMiddleware)
    return app
