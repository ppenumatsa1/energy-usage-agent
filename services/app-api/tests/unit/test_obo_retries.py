from typing import Any

import pytest

from energy_usage_app_api.application.errors import UpstreamUnavailable
from energy_usage_app_api.infrastructure import obo
from energy_usage_app_api.infrastructure.obo import EntraOboProvider
from energy_usage_shared.auth import Principal

USER = Principal(tid="t", oid="o", token="user-token")


class _Msal:
    def __init__(self, outcomes: list[dict[str, Any] | Exception]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    def acquire_token_on_behalf_of(self, user_token: str, scopes: list[str]) -> dict[str, Any]:
        self.calls += 1
        r = self.outcomes.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _provider(monkeypatch: pytest.MonkeyPatch, msal: _Msal) -> EntraOboProvider:
    async def no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(obo.asyncio, "sleep", no_sleep)
    p = EntraOboProvider("app", "tenant", "api://energy/Energy.Read", secret="s")
    p._msal = msal
    return p


async def test_transient_failures_are_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    msal = _Msal([ConnectionError("reset"), {"access_token": "tok", "expires_in": 3600}])
    assert await _provider(monkeypatch, msal).token_for(USER) == "tok"
    assert msal.calls == 2


async def test_network_failure_becomes_upstream_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    msal = _Msal([ConnectionError("reset"), ConnectionError("reset")])
    with pytest.raises(UpstreamUnavailable):
        await _provider(monkeypatch, msal).token_for(USER)


async def test_permanent_errors_are_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    msal = _Msal([{"error": "invalid_grant", "error_codes": [50013]}])
    with pytest.raises(UpstreamUnavailable) as err:
        await _provider(monkeypatch, msal).token_for(USER)
    assert msal.calls == 1 and "50013" not in str(err.value)
