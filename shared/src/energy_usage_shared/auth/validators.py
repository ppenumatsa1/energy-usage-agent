import time
from typing import Any, Protocol

import jwt

from ..settings import ServiceSettings
from .principal import AuthError, Principal

ENTRA_LOGIN = "https://login.microsoftonline.com"
DEV_ISSUER = "https://dev.energy-usage.local"


class TokenValidator(Protocol):
    def validate(self, token: str) -> Principal: ...


def bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise AuthError("missing_token")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError("malformed_authorization_header")
    return token.strip()


def _principal_from_claims(claims: dict[str, Any], required_scope: str, token: str) -> Principal:
    tid = str(claims.get("tid", "")).lower()
    oid = str(claims.get("oid", "")).lower()
    if not tid or not oid:
        raise AuthError("missing_tid_or_oid")
    scopes = frozenset(str(claims.get("scp", "")).split())
    if not scopes:
        raise AuthError("app_only_token_not_allowed")
    if required_scope and required_scope not in scopes:
        raise AuthError("missing_scope")
    name = claims.get("name") or claims.get("preferred_username")
    return Principal(tid=tid, oid=oid, name=name, scopes=scopes, token=token)


class EntraTokenValidator:
    """Validates Entra ID access tokens issued by the home tenant (single-tenant apps).

    Guests the tenant admin has invited get home-tenant tokens too.
    """

    def __init__(
        self, audience: str, tenant_id: str, required_scope: str, allowed_client_ids: frozenset[str]
    ) -> None:
        if not audience or not tenant_id or not allowed_client_ids:
            raise ValueError(
                "AUTH_AUDIENCE, AUTH_TENANT_ID and AUTH_ALLOWED_CLIENT_IDS are required for Entra auth"
            )
        self._clients = frozenset(c.lower() for c in allowed_client_ids)
        self._audiences = [audience] if audience.startswith("api://") else [audience, f"api://{audience}"]
        self._tenant = tenant_id.lower()
        self._issuers = [f"{ENTRA_LOGIN}/{self._tenant}/v2.0", f"https://sts.windows.net/{self._tenant}/"]
        self._scope = required_scope
        self._jwks = jwt.PyJWKClient(
            f"{ENTRA_LOGIN}/{self._tenant}/discovery/v2.0/keys", cache_keys=True, lifespan=3600
        )

    def validate(self, token: str) -> Principal:
        try:
            key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self._audiences,
                issuer=self._issuers,
                options={"require": ["exp", "iat", "iss", "aud"]},
                leeway=60,
            )
        except jwt.PyJWTError as exc:
            raise AuthError(f"invalid_token:{type(exc).__name__}") from exc
        if str(claims.get("tid", "")).lower() != self._tenant:
            raise AuthError("wrong_tenant")
        # Pre-authorization only skips consent; any client a user consents to could still get a token.
        if str(claims.get("azp") or claims.get("appid") or "").lower() not in self._clients:
            raise AuthError("client_not_allowed")
        return _principal_from_claims(claims, self._scope, token)


class DevTokenValidator:
    """LOCAL ONLY. HS256 tokens minted by scripts/dev_token.py or the app-api dev endpoint."""

    def __init__(self, secret: str, audience: str, required_scope: str) -> None:
        self._secret = secret
        self._audience = audience
        self._scope = required_scope

    def validate(self, token: str) -> Principal:
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                audience=self._audience,
                issuer=DEV_ISSUER,
                options={"require": ["exp", "iat", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthError(f"invalid_token:{type(exc).__name__}") from exc
        return _principal_from_claims(claims, self._scope, token)


def build_validator(settings: ServiceSettings) -> TokenValidator:
    if settings.auth_mode == "dev":
        assert settings.dev_jwt_secret  # guarded by ServiceSettings
        return DevTokenValidator(
            settings.dev_jwt_secret, settings.auth_audience, settings.auth_required_scope
        )
    clients = frozenset(c.strip() for c in settings.auth_allowed_client_ids.split(",") if c.strip())
    return EntraTokenValidator(
        settings.auth_audience, settings.auth_tenant_id, settings.auth_required_scope, clients
    )


def token_expiry(token: str) -> float:
    """Unverified `exp` for cache lifetimes only. Never use for authorization."""
    try:
        return float(jwt.decode(token, options={"verify_signature": False}).get("exp", 0))
    except jwt.PyJWTError:
        return time.time()
