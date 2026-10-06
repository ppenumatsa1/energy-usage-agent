"""GET /v1/me on the energy-service, cached briefly per user (onboarding check, BR-2)."""

import time

import httpx

from energy_usage_shared.auth import Principal
from energy_usage_shared.contracts import Me
from energy_usage_shared.telemetry import CORRELATION_HEADER, get_correlation_id

from ..application.errors import UpstreamUnavailable

TTL_SECONDS = 300


class HttpProfileClient:
    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=10)
        self._cache: dict[str, tuple[Me, float]] = {}

    async def me(self, principal: Principal, token: str) -> Me:
        hit = self._cache.get(principal.key)
        if hit and hit[1] > time.monotonic():
            return hit[0]
        headers = {"Authorization": f"Bearer {token}"}
        if cid := get_correlation_id():
            headers[CORRELATION_HEADER] = cid
        try:
            r = await self._client.get("/v1/me", headers=headers)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable("The energy service is unavailable.") from exc
        me = Me.model_validate(r.json())
        # Only cache positives long; a newly onboarded user should not wait 5 minutes.
        self._cache[principal.key] = (me, time.monotonic() + (TTL_SECONDS if me.onboarded else 15))
        return me

    async def ready(self) -> bool:
        try:
            r = await self._client.get("/readyz", timeout=3)
        except httpx.HTTPError:
            return False
        return r.status_code == 200

    async def aclose(self) -> None:
        await self._client.aclose()
