from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient

from energy_usage_app_api.api.app import create_app
from energy_usage_app_api.application.models import ToolCall
from energy_usage_app_api.bootstrap import build_container
from energy_usage_app_api.config import AppApiSettings
from energy_usage_app_api.testing.fake_agent import FakeAgentRunner
from energy_usage_app_api.testing.memory import MemoryConversationStore
from energy_usage_shared.auth import DEV_USERS, DevTokenValidator, Principal, mint_dev_token
from energy_usage_shared.contracts import ChartHint, Column, Me, ToolError, ToolResult

SECRET = "test-secret-test-secret-test-secret-0123"


def daily_result(n: int = 3, result_id: str = "r_daily") -> ToolResult:
    return ToolResult(
        result_id=result_id,
        tool="get_usage",
        columns=[Column(key="period", label="Period"), Column(key="kwh", label="kWh", type="number")],
        rows=[{"period": f"2026-02-0{i + 1}", "kwh": 100.0 + i} for i in range(n)],
        tz="America/Chicago",
        assumptions=["2026-02-01 to 2026-02-03 (America/Chicago)."],
        summary={"total_kwh": 303.0, "periods": n},
        chart_hint=ChartHint(type="bar", x="period", y=["kwh"], title="Usage"),
    )


class StubGateway:
    def __init__(self, results: dict[str, ToolResult | ToolError]) -> None:
        self.results = results
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolCall:
        self.calls.append((name, arguments))
        r = self.results.get(name, daily_result())
        return (
            ToolCall(name, arguments, error=r)
            if isinstance(r, ToolError)
            else ToolCall(name, arguments, result=r)
        )


class StubGatewayFactory:
    def __init__(self, gateway: StubGateway) -> None:
        self.gateway = gateway
        self.opened: list[tuple[str, str]] = []

    @asynccontextmanager
    async def open(self, user_token: str, correlation_id: str) -> AsyncIterator[StubGateway]:
        self.opened.append((user_token, correlation_id))
        yield self.gateway


class StubObo:
    async def token_for(self, principal: Principal) -> str:
        return f"obo-for-{principal.oid}"


class StubProfile:
    async def me(self, principal: Principal, token: str) -> Me:
        if principal.oid == DEV_USERS["x1"].oid:
            return Me(onboarded=False)
        return Me(onboarded=True, customer_name="Demo Customer", timezone="America/Chicago")

    async def ready(self) -> bool:
        return True


def settings(**overrides: Any) -> AppApiSettings:
    base: dict[str, Any] = {
        "environment": "test",
        "auth_mode": "dev",
        "dev_jwt_secret": SECRET,
        "auth_audience": "app-api",
        "agent_mode": "fake",
        "obo_credential": "dev",
        "history_purge_interval_minutes": 0,  # tests run the purge explicitly
    }
    return AppApiSettings(**{**base, **overrides})


@pytest.fixture
def gateway() -> StubGateway:
    return StubGateway({})


def make_client(gateway: StubGateway, **overrides: Any) -> TestClient:
    """A test client with stubs; pass agent=..., conversations=... or settings fields to override."""
    parts: dict[str, Any] = {
        "agent": overrides.pop("agent", None) or FakeAgentRunner(),
        "conversations": overrides.pop("conversations", None) or MemoryConversationStore(),
    }
    container = build_container(
        settings(**{"rate_limit_per_minute": 5, **overrides}),
        validator=DevTokenValidator(SECRET, "app-api", "Chat.Ask"),
        tools=StubGatewayFactory(gateway),
        obo=StubObo(),
        profile=StubProfile(),
        **parts,
    )
    return TestClient(create_app(container))


@pytest.fixture
def client_factory(gateway: StubGateway):  # type: ignore[no-untyped-def]
    return lambda **overrides: make_client(gateway, **overrides)


@pytest.fixture
def client(gateway: StubGateway):  # type: ignore[no-untyped-def]
    with make_client(gateway) as c:
        yield c


@pytest.fixture(scope="session")
def auth():  # type: ignore[no-untyped-def]
    def _auth(user: str, scope: str = "Chat.Ask") -> dict[str, str]:
        u = DEV_USERS[user]
        return {"Authorization": f"Bearer {mint_dev_token(SECRET, 'app-api', scope, u.tid, u.oid, u.name)}"}

    return _auth


@pytest.fixture(scope="session")
def make_settings():  # type: ignore[no-untyped-def]
    return settings
