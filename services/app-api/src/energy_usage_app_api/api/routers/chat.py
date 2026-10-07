import contextlib
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
    """Errors after the headers are sent become an `error` event (problem body with correlationId)."""
    send, receive = anyio.create_memory_object_stream[dict[str, str]](32)
    log_extra = {"correlation_id": prepared.correlation_id}

    async def emit(event: str, data: dict[str, Any]) -> None:
        await send.send({"event": event, "data": json.dumps(data)})

    async def emit_problem(status: int, code: str, title: str, detail: str | None = None) -> None:
        body = problem_body(status, code, title, detail)
        body["correlationId"] = body["correlationId"] or prepared.correlation_id
        with contextlib.suppress(anyio.BrokenResourceError, anyio.ClosedResourceError):
            await emit("error", body)

    async def worker() -> None:
        async with send:
            try:
                result = await service.answer(prepared, emit)
                await send.send({"event": "result", "data": result.model_dump_json(by_alias=True)})
            except anyio.get_cancelled_exc_class():
                _log.info("chat_cancelled", extra={"event": "chat_cancelled", **log_extra})
                raise
            except (anyio.BrokenResourceError, anyio.ClosedResourceError):  # the client went away
                _log.info("chat_cancelled", extra={"event": "chat_cancelled", **log_extra})
            except ChatError as exc:
                _log.warning("chat_failed", extra={"event": "chat_failed", "code": exc.code, **log_extra})
                await emit_problem(exc.status, exc.code, exc.title, exc.detail)
            except Exception:
                _log.exception(
                    "chat_failed", extra={"event": "chat_failed", "code": "internal_error", **log_extra}
                )
                await emit_problem(500, "internal_error", "Something went wrong")

    async with anyio.create_task_group() as tg:
        tg.start_soon(worker)
        async with receive:
            async for item in receive:
                yield item
