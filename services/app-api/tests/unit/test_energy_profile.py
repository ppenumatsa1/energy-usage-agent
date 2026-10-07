import httpx
import pytest

from energy_usage_app_api.application.errors import UpstreamUnavailable
from energy_usage_app_api.infrastructure import energy_profile
from energy_usage_app_api.infrastructure.energy_profile import HttpProfileClient
from energy_usage_shared.auth import Principal

USER = Principal(tid="t", oid="o")


def _client(monkeypatch: pytest.MonkeyPatch, replies: list[httpx.Response | Exception]) -> HttpProfileClient:
    monkeypatch.setattr(energy_profile, "RETRY_BACKOFF_SECONDS", 0)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        r = replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    http = httpx.AsyncClient(base_url="http://energy-service", transport=httpx.MockTransport(handler))
    client = HttpProfileClient("http://energy-service", http)
    client.seen = seen  # type: ignore[attr-defined]
    return client


async def test_transient_failures_are_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(
        monkeypatch,
        [httpx.ConnectError("down"), httpx.Response(503), httpx.Response(200, json={"onboarded": True})],
    )
    assert (await client.me(USER, "tok")).onboarded
    assert len(client.seen) == 3  # type: ignore[attr-defined]


async def test_client_errors_are_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch, [httpx.Response(401)])
    with pytest.raises(UpstreamUnavailable):
        await client.me(USER, "tok")
    assert len(client.seen) == 1  # type: ignore[attr-defined]


async def test_unexpected_body_is_upstream_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch, [httpx.Response(200, text="<html>")])
    with pytest.raises(UpstreamUnavailable):
        await client.me(USER, "tok")
