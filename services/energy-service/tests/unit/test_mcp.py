from typing import Any

from fastapi.testclient import TestClient

from energy_usage_shared.contracts import TOOL_NAMES, parse_tool_error

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def rpc(client: TestClient, token: str | None, method: str, params: dict[str, Any] | None = None) -> Any:
    headers = dict(HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.post(
        "/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    )


def call(client: TestClient, token: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    r = rpc(client, token, "tools/call", {"name": name, "arguments": args})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def test_mcp_requires_token(client: TestClient) -> None:
    r = rpc(client, None, "tools/list")
    assert r.status_code == 401 and r.json()["code"] == "unauthorized"


def test_list_tools_matches_contract(client: TestClient, token) -> None:  # type: ignore[no-untyped-def]
    r = rpc(client, token("a1"), "tools/list")
    tools = r.json()["result"]["tools"]
    assert {t["name"] for t in tools} == set(TOOL_NAMES)
    for t in tools:
        names = _property_names(t["inputSchema"])
        assert not {n for n in names if "customer" in n.lower() or n.lower() in {"tid", "oid", "tenant_id"}}


def _property_names(schema: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(schema, dict):
        out |= set(schema.get("properties", {}))
        for v in schema.values():
            out |= _property_names(v)
    elif isinstance(schema, list):
        for v in schema:
            out |= _property_names(v)
    return out


def test_call_tool_returns_structured_result(client: TestClient, token) -> None:  # type: ignore[no-untyped-def]
    res = call(
        client, token("a2"), "get_usage", {"start": "last_month", "end": "last_month", "granularity": "month"}
    )
    assert not res.get("isError")
    data = res["structuredContent"]
    assert data["tool"] == "get_usage" and data["tz"] == "America/New_York" and len(data["rows"]) == 1


def test_compare_tool_nested_periods(client: TestClient, token) -> None:  # type: ignore[no-untyped-def]
    res = call(
        client,
        token("a1"),
        "compare_usage",
        {
            "period_a": {"start": "this_month", "end": "this_month"},
            "period_b": {"start": "last_month", "end": "last_month"},
        },
    )
    assert not res.get("isError"), res
    assert res["structuredContent"]["summary"]["delta_kwh"] is not None


def test_tool_errors_are_readable(client: TestClient, token) -> None:  # type: ignore[no-untyped-def]
    res = call(client, token("x1"), "get_usage", {"start": "today", "end": "today"})
    assert res["isError"] is True
    assert parse_tool_error(res["content"][0]["text"]).code == "not_onboarded"


def test_isolation_over_mcp(client: TestClient, token) -> None:  # type: ignore[no-untyped-def]
    a = call(client, token("a1"), "list_sites_and_meters", {})["structuredContent"]
    b = call(client, token("b1"), "list_sites_and_meters", {})["structuredContent"]
    assert {r["meter_id"] for r in a["rows"]}.isdisjoint({r["meter_id"] for r in b["rows"]})
