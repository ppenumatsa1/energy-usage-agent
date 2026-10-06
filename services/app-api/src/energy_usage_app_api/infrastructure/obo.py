"""On-behalf-of token exchange: user token for app-api -> user token for energy-service (identity option B)."""

import asyncio
import logging
import time

from energy_usage_shared.auth import Principal, mint_dev_token
from energy_usage_shared.auth.validators import token_expiry

from ..application.errors import UpstreamUnavailable

_log = logging.getLogger("energy_usage.auth")
FEDERATION_SCOPE = "api://AzureADTokenExchange/.default"
_REFRESH_MARGIN = 120


class _Cache:
    def __init__(self) -> None:
        self._items: dict[str, tuple[str, float]] = {}

    def get(self, key: str) -> str | None:
        hit = self._items.get(key)
        if hit and hit[1] - _REFRESH_MARGIN > time.time():
            return hit[0]
        return None

    def put(self, key: str, token: str, expires_at: float) -> None:
        if len(self._items) > 5000:
            now = time.time()
            self._items = {k: v for k, v in self._items.items() if v[1] > now}
        self._items[key] = (token, expires_at)


class EntraOboProvider:
    """MSAL confidential client for the home tenant. Credential is either a client secret or a
    managed-identity token used as a federated client assertion (no secret in Azure)."""

    def __init__(
        self,
        client_id: str,
        tenant_id: str,
        scope: str,
        *,
        secret: str | None = None,
        mi_client_id: str | None = None,
    ):
        self._client_id = client_id
        self._authority = f"https://login.microsoftonline.com/{tenant_id}"
        self._scope = scope
        self._secret = secret
        self._mi_client_id = mi_client_id
        self._msal: object | None = None
        self._cache = _Cache()

    def _app(self):  # type: ignore[no-untyped-def]
        if self._msal is None:
            import msal

            credential: object = self._secret
            if not credential:
                from azure.identity import ManagedIdentityCredential

                mi = ManagedIdentityCredential(client_id=self._mi_client_id)
                credential = {"client_assertion": lambda: mi.get_token(FEDERATION_SCOPE).token}
            self._msal = msal.ConfidentialClientApplication(
                self._client_id, client_credential=credential, authority=self._authority
            )
        return self._msal

    async def token_for(self, principal: Principal) -> str:
        cached = self._cache.get(principal.key)
        if cached:
            return cached
        result = await asyncio.to_thread(
            self._app().acquire_token_on_behalf_of, principal.token, [self._scope]
        )
        token = result.get("access_token")
        if not token:
            # error codes only; never log tokens or the error description
            error = result.get("error", "unknown")
            codes = ",".join(f"AADSTS{c}" for c in result.get("error_codes") or [])
            _log.warning("obo_failed", extra={"event": "obo_failed", "error": error, "error_codes": codes})
            raise UpstreamUnavailable(f"Token exchange failed ({error} {codes}).")
        self._cache.put(principal.key, token, time.time() + int(result.get("expires_in", 300)))
        return token


class DevOboProvider:
    """LOCAL ONLY: mints an energy-service dev token for the same (tid, oid)."""

    def __init__(self, secret: str, audience: str, scope: str) -> None:
        self._secret, self._audience, self._scope = secret, audience, scope

    async def token_for(self, principal: Principal) -> str:
        return mint_dev_token(
            self._secret, self._audience, self._scope, principal.tid, principal.oid, principal.name
        )


__all__ = ["DevOboProvider", "EntraOboProvider", "token_expiry"]
