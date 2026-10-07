"""Failure paths: database outages, timeouts and bugs never leak internals over REST or MCP."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg_pool import PoolTimeout

from energy_usage_energy.application.errors import DataUnavailable, QueryTimeout
from energy_usage_energy.infrastructure.postgres import PgCustomerDirectory, PgUsageRepository, rls_session
from energy_usage_shared.contracts import parse_tool_error

SECRET_TEXT = "db-host.internal.example password=hunter2 SELECT * FROM energy"


class FailingRepository:
    def __init__(self, exc: Exception, ping: bool | Exception = True) -> None:
        self.exc, self._ping = exc, ping

    @asynccontextmanager
    async def scoped(self, customer_id: Any) -> AsyncIterator[Any]:
        raise self.exc
        yield  # pragma: no cover

    async def ping(self) -> bool:
        if isinstance(self._ping, Exception):
            raise self._ping
        return self._ping


@pytest.fixture
def failing(request: pytest.FixtureRequest, client_for) -> TestClient:  # type: ignore[no-untyped-def]
    return client_for(FailingRepository(*request.param))  # type: ignore[no-any-return]


def call(client: TestClient, token: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    r = client.post(
        "/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {token}",
            "x-correlation-id": "corr-mcp-test",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}},
    )
    assert r.status_code == 200, r.text
    return r.json()["result"]  # type: ignore[no-any-return]


def _auth(token: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {token('a1')}"}


USAGE = {"start": "last_month", "end": "last_month"}


@pytest.mark.parametrize("failing", [(DataUnavailable(),), (QueryTimeout(),)], indirect=True)
def test_db_outage_is_503_problem(failing: TestClient, token) -> None:  # type: ignore[no-untyped-def]
    r = failing.get("/v1/usage", params=USAGE, headers=_auth(token))
    assert r.status_code == 503
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.headers["retry-after"] == "5"
    body = r.json()
    assert body["code"] == "upstream_unavailable" and body["title"] == "Service temporarily unavailable"
    assert body["correlationId"] == r.headers["x-correlation-id"]


@pytest.mark.parametrize("failing", [(RuntimeError(SECRET_TEXT),)], indirect=True)
def test_unexpected_error_is_generic_500_with_correlation_id(
    failing: TestClient, token, caplog: pytest.LogCaptureFixture
) -> None:  # type: ignore[no-untyped-def]
    r = failing.get("/v1/usage", params=USAGE, headers={**_auth(token), "x-correlation-id": "corr-500-test"})
    assert r.status_code == 500
    assert "hunter2" not in r.text and "internal.example" not in r.text and "SELECT" not in r.text
    assert r.json()["code"] == "internal_error"
    assert r.json()["correlationId"] == "corr-500-test" == r.headers["x-correlation-id"]
    rec = next(rec for rec in caplog.records if rec.getMessage() == "unhandled_error")
    assert rec.exc_info and rec.correlation_id == "corr-500-test" and rec.event == "unhandled_error"  # type: ignore[attr-defined]


@pytest.mark.parametrize("failing", [(DataUnavailable(),)], indirect=True)
def test_db_outage_over_mcp_is_retryable_tool_error(failing: TestClient, token) -> None:  # type: ignore[no-untyped-def]
    res = call(failing, token("a1"), "get_usage", USAGE)
    assert res["isError"] is True
    err = parse_tool_error(res["content"][0]["text"])
    assert err.code == "internal" and "try again" in err.message.lower()


@pytest.mark.parametrize("failing", [(RuntimeError(SECRET_TEXT),)], indirect=True)
def test_unexpected_error_over_mcp_is_generic(
    failing: TestClient, token, caplog: pytest.LogCaptureFixture
) -> None:  # type: ignore[no-untyped-def]
    res = call(failing, token("a1"), "list_sites_and_meters", {})
    assert res["isError"] is True and "hunter2" not in str(res)
    assert parse_tool_error(res["content"][0]["text"]).code == "internal"
    rec = next(r for r in caplog.records if r.getMessage() == "tool_unhandled_error")
    assert rec.exc_info and rec.correlation_id == "corr-mcp-test"  # type: ignore[attr-defined]
    # The session keeps working after a failed tool call.
    assert call(failing, token("a1"), "get_usage", USAGE)["isError"] is True


def test_invalid_tool_arguments_are_invalid_argument(client: TestClient, token) -> None:  # type: ignore[no-untyped-def]
    res = call(client, token("a1"), "get_peak_usage", {"start": "today", "end": "today", "top_n": 99})
    assert res["isError"] is True
    err = parse_tool_error(res["content"][0]["text"])
    assert err.code == "invalid_argument" and "top_n" in err.message and "99" not in err.message
    res = call(client, token("a1"), "compare_usage", {"period_a": {"start": "today"}, "period_b": "x"})
    assert parse_tool_error(res["content"][0]["text"]).code == "invalid_argument"


@pytest.mark.parametrize(
    "failing", [(DataUnavailable(), False), (DataUnavailable(), RuntimeError("boom"))], indirect=True
)
def test_readyz_reports_db_unavailable(failing: TestClient) -> None:
    r = failing.get("/readyz")
    assert r.status_code == 503 and r.json() == {"status": "unavailable"}


# ---- infrastructure mapping with a fake pool -------------------------------------------------------


class FakePool:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.timeouts: list[float | None] = []

    @asynccontextmanager
    async def connection(self, timeout: float | None = None) -> AsyncIterator[Any]:  # noqa: ASYNC109 - mirrors psycopg_pool
        self.timeouts.append(timeout)
        raise self.exc
        yield  # pragma: no cover


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (PoolTimeout("couldn't get a connection after 10.00 sec"), DataUnavailable),
        (psycopg.OperationalError("connection to server at 10.0.0.5 failed: refused"), DataUnavailable),
        (psycopg.OperationalError("Could not acquire a database access token"), DataUnavailable),
        (psycopg.InterfaceError("the connection is closed"), DataUnavailable),
        (psycopg.errors.QueryCanceled("canceling statement due to statement timeout"), QueryTimeout),
    ],
)
async def test_db_failures_map_to_domain_errors(exc: Exception, expected: type[Exception]) -> None:
    pool: Any = FakePool(exc)
    with pytest.raises(expected) as info:
        async with rls_session(pool, uuid4()):
            pass  # pragma: no cover
    assert type(info.value) is expected and "10.0.0.5" not in info.value.message  # type: ignore[attr-defined]
    with pytest.raises(expected):
        await PgCustomerDirectory(pool).resolve(str(uuid4()), str(uuid4()))


async def test_errors_inside_rls_session_are_mapped() -> None:
    class Conn:
        def transaction(self) -> Any:
            @asynccontextmanager
            async def tx() -> AsyncIterator[None]:
                yield

            return tx()

        async def execute(self, *_: Any) -> None:
            return None

    class Pool:
        @asynccontextmanager
        async def connection(self) -> AsyncIterator[Conn]:
            yield Conn()

    pool: Any = Pool()
    with pytest.raises(QueryTimeout):
        async with rls_session(pool, uuid4()):
            raise psycopg.errors.QueryCanceled("canceling statement due to statement timeout")
    with pytest.raises(ValueError, match="not a db error"):
        async with rls_session(pool, uuid4()):
            raise ValueError("not a db error")


async def test_ping_returns_false_on_db_failure() -> None:
    pool = FakePool(PoolTimeout("timeout"))
    assert await PgUsageRepository(pool).ping() is False  # type: ignore[arg-type]
    assert pool.timeouts == [3.0]
