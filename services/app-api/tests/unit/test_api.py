import asyncio
import json
import logging
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg_pool import PoolTimeout

from energy_usage_app_api.api.routers.chat import _stream
from energy_usage_app_api.application.chat_service import PreparedChat
from energy_usage_app_api.application.errors import UpstreamUnavailable
from energy_usage_app_api.infrastructure.conversations_pg import PgConversationStore
from energy_usage_app_api.testing.fake_agent import FakeAgentRunner
from energy_usage_app_api.testing.memory import MemoryConversationStore
from energy_usage_shared.auth import Principal
from energy_usage_shared.contracts import ToolError


def test_health(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_requires_token_and_scope(client: TestClient, auth) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/me").status_code == 401
    r = client.get("/api/me", headers=auth("a1", scope="Energy.Read"))
    assert r.status_code == 401 and r.json()["code"] == "unauthorized"


def test_me(client: TestClient, auth) -> None:  # type: ignore[no-untyped-def]
    body = client.get("/api/me", headers=auth("a1")).json()
    assert body == {
        "onboarded": True,
        "customerName": "Demo Customer",
        "timezone": "America/Chicago",
        "userName": "User A1",
    }


def test_chat_json(client: TestClient, auth, gateway) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/api/chat", json={"message": "How much did I use last month?"}, headers=auth("a1"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok" and body["conversationId"] and body["correlationId"]
    assert body["table"]["rows"][0] == {"period": "2026-02-01", "kwh": 100.0}
    assert body["chart"]["x"] == "period"
    assert gateway.calls[0][0] == "get_usage"


def test_chat_sse(client: TestClient, auth) -> None:  # type: ignore[no-untyped-def]
    with client.stream(
        "POST",
        "/api/chat",
        json={"message": "usage today"},
        headers={**auth("a1"), "Accept": "text/event-stream"},
    ) as r:
        assert r.status_code == 200
        text = "".join(r.iter_text())
    events = [line.split(":", 1)[1].strip() for line in text.splitlines() if line.startswith("event:")]
    assert events[0] == "status" and events[-1] == "result"
    data = [line.split(":", 1)[1].strip() for line in text.splitlines() if line.startswith("data:")]
    assert json.loads(data[-1])["status"] == "ok"
    assert {"stage": "tool", "tool": "get_usage"} in [json.loads(d) for d in data[:-1]]


def test_refusal_has_no_table(client: TestClient, auth, gateway) -> None:  # type: ignore[no-untyped-def]
    body = client.post("/api/chat", json={"message": "What is my bill?"}, headers=auth("a1")).json()
    assert body["status"] == "refused" and body["table"] is None and not gateway.calls


def test_tool_error_becomes_no_data(client: TestClient, auth, gateway) -> None:  # type: ignore[no-untyped-def]
    gateway.results["get_usage"] = ToolError(code="no_data", message="No usage data.")
    body = client.post("/api/chat", json={"message": "usage"}, headers=auth("a1")).json()
    assert body["status"] == "no_data" and body["table"] is None


def test_not_onboarded(client: TestClient, auth) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/api/chat", json={"message": "usage"}, headers=auth("x1"))
    assert r.status_code == 403 and r.json()["code"] == "not_onboarded"


def test_validation(client: TestClient, auth) -> None:  # type: ignore[no-untyped-def]
    for bad in ({"message": ""}, {"message": "x" * 2001}, {}):
        r = client.post("/api/chat", json=bad, headers=auth("a1"))
        assert r.status_code == 422 and r.json()["code"] == "invalid_request"


def test_rate_limit(client: TestClient, auth) -> None:  # type: ignore[no-untyped-def]
    codes = [
        client.post("/api/chat", json={"message": "usage"}, headers=auth("a2")).status_code for _ in range(6)
    ]
    assert codes[:5] == [200] * 5 and codes[5] == 429
    r = client.post("/api/chat", json={"message": "usage"}, headers=auth("a2"))
    assert r.json()["code"] == "rate_limited" and int(r.headers["retry-after"]) >= 1


def test_conversation_ownership(client: TestClient, auth) -> None:  # type: ignore[no-untyped-def]
    cid = client.post("/api/chat", json={"message": "usage"}, headers=auth("a1")).json()["conversationId"]
    again = client.post(
        "/api/chat", json={"message": "and today?", "conversationId": cid}, headers=auth("a1")
    )
    assert again.json()["conversationId"] == cid
    # Another user (even in the same tenant) cannot see, continue or delete it.
    other = client.post("/api/chat", json={"message": "x", "conversationId": cid}, headers=auth("b1"))
    assert other.status_code == 404 and other.json()["code"] == "conversation_not_found"
    assert client.get("/api/conversations", headers=auth("b1")).json() == []
    assert client.delete(f"/api/conversations/{cid}", headers=auth("b1")).status_code == 404
    mine = client.get("/api/conversations", headers=auth("a1")).json()
    assert [c["conversationId"] for c in mine] == [cid] and mine[0]["title"] == "usage"
    assert client.delete(f"/api/conversations/{cid}", headers=auth("a1")).status_code == 204
    assert client.get("/api/conversations", headers=auth("a1")).json() == []


def test_dev_sign_in(client: TestClient) -> None:
    users = client.get("/api/dev/users").json()
    assert {u["id"] for u in users} == {"a1", "a2", "b1", "x1"}
    tok = client.post("/api/dev/token", json={"user": "a1"}).json()["accessToken"]
    assert client.get("/api/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 200


class BrokenPool:
    """A pool whose database is down (psycopg raises PoolTimeout, an OperationalError)."""

    def connection(self):  # type: ignore[no-untyped-def]
        @asynccontextmanager
        async def _conn():  # type: ignore[no-untyped-def]
            raise PoolTimeout("couldn't get a connection after 30.00 sec to host=db.internal")
            yield

        return _conn()


def test_database_down_is_503_without_details(client_factory, auth) -> None:  # type: ignore[no-untyped-def]
    with client_factory(conversations=PgConversationStore(BrokenPool())) as c:  # type: ignore[arg-type]
        listed = c.get("/api/conversations", headers=auth("a1"))
        follow_up = c.post(
            "/api/chat", json={"message": "usage", "conversationId": str(uuid4())}, headers=auth("a1")
        )
        status = c.get("/api/status", headers=auth("a1")).json()
    for r in (listed, follow_up):
        assert r.status_code == 503 and r.json()["code"] == "upstream_unavailable"
        assert r.json()["correlationId"] and "db.internal" not in r.text and "sec" not in r.text
    assert {s["id"]: s["status"] for s in status["components"]}["database"] == "down"


class FailingStore(MemoryConversationStore):
    async def create(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise UpstreamUnavailable("down")

    async def touch(self, conversation_id):  # type: ignore[no-untyped-def]
        raise UpstreamUnavailable("down")

    async def add_turn(self, conversation_id, turn):  # type: ignore[no-untyped-def]
        raise UpstreamUnavailable("down")


def test_answer_survives_history_save_failure(client_factory, auth, caplog) -> None:  # type: ignore[no-untyped-def]
    with client_factory(conversations=FailingStore()) as c:
        r = c.post("/api/chat", json={"message": "usage last month"}, headers=auth("a1"))
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["table"]["rows"]
    assert "history_save_failed" in caplog.text and "turn_save_failed" in caplog.text


class ExplodingAgent(FakeAgentRunner):
    async def run_turn(self, message, agent_conversation_id, tools, emit):  # type: ignore[no-untyped-def]
        await emit("status", {"stage": "tool", "tool": "get_usage"})
        raise RuntimeError("SELECT secret FROM internal_table at https://internal.example")


def test_sse_error_event_has_correlation_id_and_no_internals(client_factory, auth) -> None:  # type: ignore[no-untyped-def]
    with (
        client_factory(agent=ExplodingAgent()) as c,
        c.stream(
            "POST",
            "/api/chat",
            json={"message": "usage"},
            headers={**auth("a1"), "Accept": "text/event-stream"},
        ) as r,
    ):
        text = "".join(r.iter_text())
    events = [line.split(":", 1)[1].strip() for line in text.splitlines() if line.startswith("event:")]
    data = [json.loads(line.split(":", 1)[1]) for line in text.splitlines() if line.startswith("data:")]
    assert events[-1] == "error" and data[-1]["code"] == "internal_error" and data[-1]["status"] == 500
    assert data[-1]["correlationId"] == r.headers["x-correlation-id"]
    assert "secret" not in text and "internal.example" not in text


async def test_sse_client_disconnect_is_logged_as_cancelled(caplog) -> None:  # type: ignore[no-untyped-def]
    started = asyncio.Event()

    class SlowService:
        async def answer(self, prepared, emit):  # type: ignore[no-untyped-def]
            await emit("status", {"stage": "thinking"})
            started.set()
            await asyncio.sleep(3600)

    prepared = PreparedChat(Principal(tid="t", oid="o"), "usage", "tok", None, "cid-123")

    async def consume() -> None:
        async for _ in _stream(SlowService(), prepared):  # type: ignore[arg-type]
            pass

    caplog.set_level(logging.INFO, logger="energy_usage.chat")
    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    cancelled = [r for r in caplog.records if r.message == "chat_cancelled"]
    assert cancelled and cancelled[0].levelno == logging.INFO and cancelled[0].correlation_id == "cid-123"
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)


class UnreachableAgent(FakeAgentRunner):
    async def ready(self) -> bool:
        return False


def test_status_reports_agent_down(client_factory, auth) -> None:  # type: ignore[no-untyped-def]
    with client_factory(agent=UnreachableAgent()) as c:
        status = c.get("/api/status", headers=auth("a1")).json()
    assert {s["id"]: s["status"] for s in status["components"]}["agent"] == "down"
