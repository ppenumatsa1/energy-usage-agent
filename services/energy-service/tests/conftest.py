from contextlib import ExitStack
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from energy_usage_energy.api.app import create_app
from energy_usage_energy.application.models import Caller
from energy_usage_energy.application.service import UsageService
from energy_usage_energy.bootstrap import Container
from energy_usage_energy.config import EnergySettings
from energy_usage_energy.testing.memory import MemoryDirectory, MemoryRepository
from energy_usage_shared.auth import DEV_USERS, DevTokenValidator, mint_dev_token

# Fixed clock: Sunday 2026-03-15 18:00 UTC (13:00 in America/Chicago, a week after the US DST change).
NOW = datetime(2026, 3, 15, 18, 0, tzinfo=UTC)
DATA_END = date(2026, 3, 14)
SECRET = "test-secret-test-secret-test-secret-0123"
AUDIENCE = "energy-service"
SCOPE = "Energy.Read"


def _caller(user: str) -> Caller:
    u = DEV_USERS[user]
    return Caller(tid=u.tid, oid=u.oid)


def _token(user: str, scope: str = SCOPE, audience: str = AUDIENCE) -> str:
    u = DEV_USERS[user]
    return mint_dev_token(SECRET, audience, scope, u.tid, u.oid, u.name)


@pytest.fixture(scope="session")
def caller():  # type: ignore[no-untyped-def]
    return _caller


@pytest.fixture(scope="session")
def token():  # type: ignore[no-untyped-def]
    return _token


@pytest.fixture(scope="session")
def service() -> UsageService:
    return UsageService(MemoryDirectory(), MemoryRepository(end_day=DATA_END), clock=lambda: NOW)


def build_test_app(service: UsageService, repository: Any) -> FastAPI:
    settings = EnergySettings(
        environment="test",
        auth_mode="dev",
        dev_jwt_secret=SECRET,
        auth_audience=AUDIENCE,
        repository="memory",
    )
    container = Container(
        settings=settings,
        service=service,
        repository=repository,
        validator=DevTokenValidator(SECRET, AUDIENCE, SCOPE),
    )
    return create_app(container)


@pytest.fixture(scope="session")
def client(service: UsageService):  # type: ignore[no-untyped-def]
    with TestClient(build_test_app(service, service._repo)) as c:  # noqa: SLF001
        yield c


@pytest.fixture
def client_for():  # type: ignore[no-untyped-def]
    """A client whose service uses the given repository (e.g. one that fails). Server errors become
    500 responses instead of being re-raised, like in production."""
    with ExitStack() as stack:

        def make(repository: Any) -> TestClient:
            app = build_test_app(UsageService(MemoryDirectory(), repository, clock=lambda: NOW), repository)
            return stack.enter_context(TestClient(app, raise_server_exceptions=False))

        yield make
