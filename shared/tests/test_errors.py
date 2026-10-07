"""Shared failure handling: DB connection setup and the catch-all problem handler."""

import sys
import types

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from energy_usage_shared import db
from energy_usage_shared.problems import install_problem_handlers
from energy_usage_shared.telemetry import CorrelationIdMiddleware


async def test_entra_token_failure_is_a_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenCredential:
        def __init__(self, **_: object) -> None: ...

        async def get_token(self, *_: str) -> object:
            raise RuntimeError("IMDS endpoint 169.254.169.254 unreachable")

    fake = types.ModuleType("azure.identity.aio")
    fake.ManagedIdentityCredential = BrokenCredential  # type: ignore[attr-defined]
    fake.DefaultAzureCredential = BrokenCredential  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "azure.identity.aio", fake)
    with pytest.raises(psycopg.OperationalError) as info:
        await db.entra_connection_class("client").connect("host=db.invalid")
    assert "169.254" not in str(info.value)


def test_pool_has_explicit_timeouts() -> None:
    pool = db.build_pool(database_url="postgresql://u@localhost/x", host=None, dbname=None, user=None,
                         entra_auth=False, client_id=None, connect_timeout=4, timeout=2.5)  # fmt: skip
    assert pool.timeout == 2.5 and pool.kwargs == {"connect_timeout": 4}
    entra = db.build_pool(database_url=None, host="h", dbname="d", user="u", entra_auth=False, client_id=None)
    assert entra.timeout == db.DEFAULT_POOL_TIMEOUT_SECONDS
    assert entra.kwargs == {"connect_timeout": db.DEFAULT_CONNECT_TIMEOUT_SECONDS}


def test_unhandled_error_is_generic_and_correlated(caplog: pytest.LogCaptureFixture) -> None:
    app = FastAPI()
    install_problem_handlers(app)
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("password=hunter2 host=db.internal")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/boom", headers={"x-correlation-id": "corr-shared-1"})
    assert r.status_code == 500 and "hunter2" not in r.text
    assert r.json()["code"] == "internal_error" and r.json()["correlationId"] == "corr-shared-1"
    assert r.headers["x-correlation-id"] == "corr-shared-1"
    rec = next(rec for rec in caplog.records if rec.getMessage() == "unhandled_error")
    assert rec.exc_info and rec.correlation_id == "corr-shared-1"  # type: ignore[attr-defined]
