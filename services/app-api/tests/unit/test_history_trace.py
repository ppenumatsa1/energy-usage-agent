"""Stored history, the per-answer trace and the status endpoint."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

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


def test_retention_purges_idle_conversations(client: TestClient, auth) -> None:  # type: ignore[no-untyped-def]
    cid = client.post("/api/chat", json={"message": "usage"}, headers=auth("a1")).json()["conversationId"]
    store = client.app.state.container.chat._conversations  # type: ignore[attr-defined]
    from uuid import UUID

    key = UUID(cid)
    store._items[key] = replace(store._items[key], updated_at=datetime.now(UTC) - timedelta(days=31))
    assert client.get(f"/api/conversations/{cid}", headers=auth("a1")).status_code == 404
    assert client.get("/api/conversations", headers=auth("a1")).json() == []
    assert key not in store._items


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
