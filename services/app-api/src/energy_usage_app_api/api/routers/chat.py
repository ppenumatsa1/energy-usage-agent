import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import anyio
from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from energy_usage_shared.problems import problem_body

from ...application.chat_service import PreparedChat
from ...application.errors import ChatError
from ...application.models import ChatRequest, ChatResponse
from ..dependencies import ChatDep, PrincipalDep, correlation_id

router = APIRouter(prefix="/api", tags=["chat"])
_log = logging.getLogger("energy_usage.chat")


@router.post("/chat", response_model=ChatResponse, response_model_by_alias=True)
async def chat(request: Request, body: ChatRequest, principal: PrincipalDep, service: ChatDep) -> Any:
    """JSON by default; Server-Sent Events (status, result, error) when the client accepts text/event-stream."""
    prepared = await service.prepare(principal, body, correlation_id())  # errors here keep their HTTP status
    if "text/event-stream" in request.headers.get("accept", ""):
        return EventSourceResponse(_stream(service, prepared), ping=15)
    return await service.answer(prepared)


async def _stream(service: ChatDep, prepared: PreparedChat) -> AsyncIterator[dict[str, str]]:
    send, receive = anyio.create_memory_object_stream[dict[str, str]](32)

    async def emit(event: str, data: dict[str, Any]) -> None:
        await send.send({"event": event, "data": json.dumps(data)})

    async def worker() -> None:
        async with send:
            try:
                result = await service.answer(prepared, emit)
                await send.send({"event": "result", "data": result.model_dump_json(by_alias=True)})
            except ChatError as exc:
                await emit("error", problem_body(exc.status, exc.code, exc.title, exc.detail))
            except Exception:
                _log.exception("chat_failed")
                await emit("error", problem_body(500, "internal_error", "Something went wrong"))

    async with anyio.create_task_group() as tg:
        tg.start_soon(worker)
        async with receive:
            async for item in receive:
                yield item
