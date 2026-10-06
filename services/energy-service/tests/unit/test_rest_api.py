from fastapi.testclient import TestClient


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_health(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").status_code == 200


def test_requires_token(client: TestClient) -> None:
    r = client.get("/v1/me")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.headers["www-authenticate"].startswith("Bearer")
    assert r.json()["code"] == "unauthorized"


def test_rejects_wrong_scope_and_audience(client: TestClient, token) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/v1/me", headers=auth(token("a1", scope="Chat.Ask"))).status_code == 401
    assert client.get("/v1/me", headers=auth(token("a1", audience="app-api"))).status_code == 401


def test_me(client: TestClient, token) -> None:  # type: ignore[no-untyped-def]
    body = client.get("/v1/me", headers=auth(token("b1"))).json()
    assert body["onboarded"] is True and body["timezone"] == "Europe/London"
    assert client.get("/v1/me", headers=auth(token("x1"))).json()["onboarded"] is False


def test_usage_and_correlation_id(client: TestClient, token) -> None:  # type: ignore[no-untyped-def]
    r = client.get(
        "/v1/usage",
        params={"start": "last_month", "end": "last_month", "granularity": "month"},
        headers={**auth(token("a1")), "x-correlation-id": "test-corr-1"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["x-correlation-id"] == "test-corr-1"
    assert r.json()["tool"] == "get_usage" and len(r.json()["rows"]) == 1


def test_not_onboarded_is_403(client: TestClient, token) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/v1/usage", params={"start": "today", "end": "today"}, headers=auth(token("x1")))
    assert r.status_code == 403 and r.json()["code"] == "not_onboarded"


def test_invalid_range_is_400(client: TestClient, token) -> None:  # type: ignore[no-untyped-def]
    r = client.get(
        "/v1/usage", params={"start": "2099-01-01", "end": "2099-01-02"}, headers=auth(token("a1"))
    )
    assert r.status_code == 400 and r.json()["code"] == "invalid_range"


def test_validation_error_is_problem(client: TestClient, token) -> None:  # type: ignore[no-untyped-def]
    r = client.get(
        "/v1/usage/peaks", params={"start": "today", "end": "today", "top_n": 99}, headers=auth(token("a1"))
    )
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"


def test_no_customer_id_parameters_anywhere(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    names = {
        p["name"].lower()
        for path in spec["paths"].values()
        for op in path.values()
        for p in op.get("parameters", [])
    }
    assert not {n for n in names if "customer" in n or n in {"tid", "oid", "tenant_id"}}


def test_tenant_isolation_over_rest(client: TestClient, token) -> None:  # type: ignore[no-untyped-def]
    sites_a = client.get("/v1/sites", headers=auth(token("a1"))).json()
    sites_b = client.get("/v1/sites", headers=auth(token("b1"))).json()
    ids_a = {r["site_id"] for r in sites_a["rows"]}
    ids_b = {r["site_id"] for r in sites_b["rows"]}
    assert ids_a and ids_b and not ids_a & ids_b
    r = client.get(
        "/v1/usage",
        params={"start": "last_month", "end": "last_month", "site_id": "S-301"},
        headers=auth(token("a1")),
    )
    assert r.status_code == 400 and r.json()["code"] == "invalid_argument"
