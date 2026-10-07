"""Stored history, the per-answer trace and the status endpoint."""

import asyncio
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient

from energy_usage_app_api.application.chat_service import ChatService
from energy_usage_app_api.testing.fake_agent import FakeAgentRunner
from energy_usage_app_api.testing.memory import MemoryConversationStore
from energy_usage_shared.contracts import ToolError


def test_answer_has_trace_and_created_at(client: TestClient, auth) -> None:  # type: ignore[no-untyped-def]
    body = client.post("/api/chat", json={"message": "usage last 30 days"}, headers=auth("a1")).json()
    trace = body["trace"]
    assert body["createdAt"] and trace["agent"] == "fake" and trace["durationMs"] >= 0
    [step] = trace["steps"]
    assert step["tool"] == "get_usage" and step["status"] == "ok" and step["rows"] == 3
    assert step["arguments"]["granularity"] == "day" and step["durationMs"] >= 0
    assert step["resultId"] and trace["resultIds"] == [step["resultId"]]
    names = {c["name"]: c["outcome"] for c in trace["checks"]}
    assert names["Numbers from tools"] == "pass" and names["Energy topics only"] == "pass"


def test_trace_for_refusal_and_tool_error(client: TestClient, auth, gateway) -> None:  # type: ignore[no-untyped-def]
    refused = client.post("/api/chat", json={"message": "what is my bill?"}, headers=auth("a1")).json()
    assert refused["trace"]["steps"] == []
    assert {c["name"]: c["outcome"] for c in refused["trace"]["checks"]}["Energy topics only"] == "blocked"
    gateway.results["get_usage"] = ToolError(code="no_data", message="No readings.")
    nodata = client.post("/api/chat", json={"message": "usage"}, headers=auth("a1")).json()
    [step] = nodata["trace"]["steps"]
    assert step["status"] == "error" and step["errorCode"] == "no_data" and step["rows"] is None
    assert step["errorMessage"] == "No readings." and step["resultId"] is None
    assert any(c["name"] == "Tool errors handled" for c in nodata["trace"]["checks"])


def test_history_round_trip_and_ownership(client: TestClient, auth) -> None:  # type: ignore[no-untyped-def]
    first = client.post("/api/chat", json={"message": "usage last month"}, headers=auth("a1")).json()
    cid = first["conversationId"]
    second = client.post(
        "/api/chat", json={"message": "what were my peak days?", "conversationId": cid}, headers=auth("a1")
    ).json()
    detail = client.get(f"/api/conversations/{cid}", headers=auth("a1"))
    assert detail.status_code == 200
    d = detail.json()
    assert d["title"] == "usage last month"
    assert [t["question"] for t in d["turns"]] == ["usage last month", "what were my peak days?"]
    assert d["turns"][0]["response"] == first and d["turns"][1]["response"] == second
    [summary] = client.get("/api/conversations", headers=auth("a1")).json()
    assert summary["turnCount"] == 2 and summary["updatedAt"] >= summary["createdAt"]
    missing = client.get(f"/api/conversations/{cid}", headers=auth("b1"))
    assert missing.status_code == 404 and missing.json()["code"] == "conversation_not_found"
    assert client.delete(f"/api/conversations/{cid}", headers=auth("a1")).status_code == 204
    assert client.get(f"/api/conversations/{cid}", headers=auth("a1")).status_code == 404


def _expire(client: TestClient, cid: str, days: int = 31) -> None:
    store = client.app.state.container.chat._conversations  # type: ignore[attr-defined]
    key = UUID(cid)
    store._items[key] = replace(store._items[key], updated_at=datetime.now(UTC) - timedelta(days=days))


def test_expired_conversation_is_gone_before_it_is_purged(client: TestClient, auth) -> None:  # type: ignore[no-untyped-def]
    cid = client.post("/api/chat", json={"message": "usage"}, headers=auth("a1")).json()["conversationId"]
    _expire(client, cid)
    assert client.get(f"/api/conversations/{cid}", headers=auth("a1")).status_code == 404
    assert client.get("/api/conversations", headers=auth("a1")).json() == []
    follow_up = client.post(
        "/api/chat", json={"message": "and today?", "conversationId": cid}, headers=auth("a1")
    )
    assert follow_up.status_code == 404 and follow_up.json()["code"] == "conversation_not_found"


class ForgetfulAgent(FakeAgentRunner):
    def __init__(self, hang: bool = False) -> None:
        self.forgotten: list[str] = []
        self.hang = hang

    async def forget(self, agent_conversation_id: str) -> None:
        if self.hang:
            await asyncio.sleep(3600)
        self.forgotten.append(agent_conversation_id)


def test_purge_runs_in_batches_off_the_request_path(client_factory, auth) -> None:  # type: ignore[no-untyped-def]
    agent = ForgetfulAgent()
    with client_factory(agent=agent, history_purge_batch_size=2, rate_limit_per_minute=50) as c:
        cids = [
            c.post("/api/chat", json={"message": "usage"}, headers=auth("a1")).json()["conversationId"]
            for _ in range(3)
        ]
        for cid in cids:
            _expire(c, cid)
        store = c.app.state.container.chat._conversations  # type: ignore[attr-defined]
        c.get("/api/conversations", headers=auth("a1"))
        assert len(store._items) == 3  # listing no longer purges
        purge = c.app.state.container.chat.purge_expired  # type: ignore[attr-defined]
        assert c.portal.call(purge) == 2 and c.portal.call(purge) == 1 and c.portal.call(purge) == 0  # type: ignore[union-attr]
        assert store._items == {} and len(agent.forgotten) == 3


def test_background_purge_runs_and_stops_with_the_app(client_factory, auth) -> None:  # type: ignore[no-untyped-def]
    agent = ForgetfulAgent()
    with client_factory(agent=agent, history_purge_interval_minutes=0.002) as c:
        cid = c.post("/api/chat", json={"message": "usage"}, headers=auth("a1")).json()["conversationId"]
        _expire(c, cid)
        deadline = time.monotonic() + 5
        while not agent.forgotten and time.monotonic() < deadline:
            time.sleep(0.02)
        assert len(agent.forgotten) == 1
    # leaving the context ran the lifespan shutdown, which cancelled the purge task without hanging


async def test_purge_forget_is_bounded_by_a_timeout() -> None:
    store = MemoryConversationStore()
    for _ in range(3):
        rec = await store.create("t", "o", "agent-conv", "old")
        store._items[rec.conversation_id] = replace(rec, updated_at=datetime.now(UTC) - timedelta(days=40))
    service = ChatService(
        agent=ForgetfulAgent(hang=True), tools=None, obo=None, profile=None,  # type: ignore[arg-type]
        conversations=store, limiter=None, forget_timeout_s=0.05,  # type: ignore[arg-type]
    )  # fmt: skip
    assert await asyncio.wait_for(service.purge_expired(), 2) == 3
    assert store._items == {}


class NewThreadAgent(FakeAgentRunner):
    """Starts a fresh agent conversation on its second turn (like the Foundry self-heal)."""

    def __init__(self) -> None:
        self.seen: list[str | None] = []

    async def run_turn(self, message, agent_conversation_id, tools, emit):  # type: ignore[no-untyped-def]
        self.seen.append(agent_conversation_id)
        turn = await super().run_turn(message, agent_conversation_id, tools, emit)
        if len(self.seen) == 2:
            turn.agent_conversation_id = "fresh-thread"
        return turn


def test_changed_agent_conversation_is_persisted(client_factory, auth) -> None:  # type: ignore[no-untyped-def]
    agent = NewThreadAgent()
    with client_factory(agent=agent) as c:
        cid = c.post("/api/chat", json={"message": "usage"}, headers=auth("a1")).json()["conversationId"]
        for q in ("and today?", "and last month?"):
            r = c.post("/api/chat", json={"message": q, "conversationId": cid}, headers=auth("a1"))
            assert r.status_code == 200 and r.json()["conversationId"] == cid
        store = c.app.state.container.chat._conversations  # type: ignore[attr-defined]
        assert store._items[UUID(cid)].agent_conversation_id == "fresh-thread"
    assert agent.seen[0] is None and agent.seen[1].startswith("fake_")
    assert agent.seen[2] == "fresh-thread"  # the follow-up continues the new thread


def test_status(client: TestClient, auth) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/status").status_code == 401
    body = client.get("/api/status", headers=auth("x1")).json()  # works before onboarding
    assert body["historyRetentionDays"] == 30
    assert {c["id"]: c["status"] for c in body["components"]} == {
        "api": "ok",
        "energy": "ok",
        "database": "ok",
        "agent": "ok",
    }
