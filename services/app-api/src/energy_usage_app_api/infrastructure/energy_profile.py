"""GET /v1/me on the energy-service, cached briefly per user (onboarding check, BR-2)."""

import asyncio
import logging
import time

import httpx
from pydantic import ValidationError

from energy_usage_shared.auth import Principal
from energy_usage_shared.contracts import Me
from energy_usage_shared.telemetry import CORRELATION_HEADER, get_correlation_id

from ..application.errors import UpstreamUnavailable

_log = logging.getLogger("energy_usage.energy_profile")
TTL_SECONDS = 300
TIMEOUT = httpx.Timeout(10, connect=5)
ATTEMPTS = 3  # GET is idempotent: retry timeouts, connection errors, 429 and 5xx
RETRY_BACKOFF_SECONDS = 0.5


def _transient(exc: httpx.HTTPError) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


class HttpProfileClient:
    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=TIMEOUT)
        self._cache: dict[str, tuple[Me, float]] = {}

    async def me(self, principal: Principal, token: str) -> Me:
        hit = self._cache.get(principal.key)
        if hit and hit[1] > time.monotonic():
            return hit[0]
        headers = {"Authorization": f"Bearer {token}"}
        if cid := get_correlation_id():
            headers[CORRELATION_HEADER] = cid
        me = await self._fetch_me(headers)
        # Only cache positives long; a newly onboarded user should not wait 5 minutes.
        self._cache[principal.key] = (me, time.monotonic() + (TTL_SECONDS if me.onboarded else 15))
        return me

    async def _fetch_me(self, headers: dict[str, str]) -> Me:
        for attempt in range(1, ATTEMPTS + 1):
            try:
                r = await self._client.get("/v1/me", headers=headers)
                r.raise_for_status()
                return Me.model_validate(r.json())
            except httpx.HTTPError as exc:
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                _log.warning(
                    "energy_profile_failed",
                    extra={
                        "event": "energy_profile_failed",
                        "attempt": attempt,
                        "error": type(exc).__name__,
                        "status_code": status,
                    },
                )
                if attempt == ATTEMPTS or not _transient(exc):
                    raise UpstreamUnavailable(
                        "The energy service is unavailable. Try again in a moment."
                    ) from exc
            except (ValueError, ValidationError) as exc:
                _log.warning(
                    "energy_profile_invalid",
                    extra={"event": "energy_profile_invalid", "error": type(exc).__name__},
                )
                raise UpstreamUnavailable("The energy service returned an unexpected response.") from exc
            await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)
        raise AssertionError("unreachable")

    async def ready(self) -> bool:
        try:
            r = await self._client.get("/readyz", timeout=3)
        except httpx.HTTPError:
            return False
        return r.status_code == 200

    async def aclose(self) -> None:
        await self._client.aclose()
