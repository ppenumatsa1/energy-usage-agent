from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI

from energy_usage_shared.telemetry import FASTAPI_TELEMETRY, CorrelationIdMiddleware

from ..bootstrap import Container
from ..mcp.server import build_mcp_app
from .errors import install_error_handlers
from .routers import coverage, health, me, meters, usage


def create_app(container: Container) -> FastAPI:
    mcp, mcp_asgi = build_mcp_app(container.service, container.validator)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            if container.pool is not None:
                await container.pool.open(wait=False)
                stack.push_async_callback(container.pool.close)
            await stack.enter_async_context(mcp.session_manager.run())
            yield

    app = FastAPI(title="energy-service", version="0.1.0", lifespan=lifespan, telemetry=FASTAPI_TELEMETRY)
    app.state.container = container
    install_error_handlers(app)
    for r in (health.router, me.router, usage.router, meters.router, coverage.router):
        app.include_router(r)
    # MCP lives at /mcp. Mounted last so REST routes match first.
    app.mount("/", mcp_asgi)
    app.add_middleware(CorrelationIdMiddleware)
    return app
