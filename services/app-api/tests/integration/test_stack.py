"""app-api -> (dev OBO token) -> real energy-service over HTTP + MCP (memory repository). No Azure needed."""

import socket
import threading
import time
from collections.abc import Iterator

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from energy_usage_app_api.api.app import create_app
from energy_usage_app_api.bootstrap import build_container

SECRET = "test-secret-test-secret-test-secret-0123"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def energy_url() -> Iterator[str]:
    from energy_usage_energy.api.app import create_app as create_energy_app
    from energy_usage_energy.bootstrap import build_container as build_energy
    from energy_usage_energy.config import EnergySettings

    settings = EnergySettings(
        environment="test",
        auth_mode="dev",
        dev_jwt_secret=SECRET,
        auth_audience="energy-service",
        repository="memory",
    )
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_energy_app(build_energy(settings)), host="127.0.0.1", port=port, log_level="warning"
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{url}/healthz").status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    yield url
    server.should_exit = True
    thread.join(5)


@pytest.fixture(scope="module")
def client(energy_url: str, make_settings) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    container = build_container(make_settings(energy_service_url=energy_url))
    with TestClient(create_app(container)) as c:
        yield c


@pytest.mark.parametrize(
    ("question", "first_key"),
    [
        ("How much did I use last month?", "period"),
        ("Compare this month vs last month", "step"),
        ("What were my peak days?", "rank"),
        ("Break down usage by site", "group_id"),
        ("Which meters do I have?", "site_id"),
    ],
)
def test_end_to_end_questions(client: TestClient, auth, question: str, first_key: str) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/api/chat", json={"message": question}, headers=auth("a1"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok", body
    assert body["table"]["columns"][0]["key"] == first_key
    assert body["table"]["rows"]


def test_me_goes_through_energy_service(client: TestClient, auth) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/me", headers=auth("b1")).json()["timezone"] == "Europe/London"
    assert client.get("/api/me", headers=auth("x1")).json()["onboarded"] is False


def test_users_only_see_their_own_meters(client: TestClient, auth) -> None:  # type: ignore[no-untyped-def]
    a = client.post("/api/chat", json={"message": "Which meters do I have?"}, headers=auth("a1")).json()
    b = client.post("/api/chat", json={"message": "Which meters do I have?"}, headers=auth("b1")).json()
    meters_a = {row["meter_id"] for row in a["table"]["rows"]}
    meters_b = {row["meter_id"] for row in b["table"]["rows"]}
    assert meters_a and meters_b and meters_a.isdisjoint(meters_b)


def test_correlation_id_propagates(client: TestClient, auth) -> None:  # type: ignore[no-untyped-def]
    r = client.post(
        "/api/chat",
        json={"message": "usage last month"},
        headers={**auth("a1"), "x-correlation-id": "corr-e2e-0001"},
    )
    assert r.json()["correlationId"] == "corr-e2e-0001"
