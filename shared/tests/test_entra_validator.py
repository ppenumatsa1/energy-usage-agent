import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from energy_usage_shared.auth import AuthError
from energy_usage_shared.auth.validators import EntraTokenValidator

AUD = "api://app-api"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(tid: str, scp: str = "Chat.Ask", iss: str | None = None) -> str:
    now = int(time.time())
    claims = {
        "aud": AUD,
        "iss": iss or f"https://login.microsoftonline.com/{tid}/v2.0",
        "iat": now,
        "exp": now + 600,
        "tid": tid,
        "oid": "user-1",
        "scp": scp,
    }
    return jwt.encode(claims, KEY, algorithm="RS256")


HOME = "home-tenant"


def _validator() -> EntraTokenValidator:
    v = EntraTokenValidator(AUD, HOME, "Chat.Ask")
    v._jwks = SimpleNamespace(get_signing_key_from_jwt=lambda _t: SimpleNamespace(key=KEY.public_key()))  # type: ignore[assignment]
    return v


def test_accepts_home_tenant_tokens() -> None:
    assert _validator().validate(_token(HOME)).tid == HOME


def test_rejects_other_tenant_issuer() -> None:
    with pytest.raises(AuthError) as exc:
        _validator().validate(_token("other-tenant"))
    assert exc.value.reason == "invalid_token:InvalidIssuerError"


def test_rejects_tid_that_does_not_match_issuer() -> None:
    with pytest.raises(AuthError) as exc:
        _validator().validate(_token("other-tenant", iss=f"https://login.microsoftonline.com/{HOME}/v2.0"))
    assert exc.value.reason == "wrong_tenant"


def test_scope_still_required() -> None:
    with pytest.raises(AuthError) as exc:
        _validator().validate(_token(HOME, scp="Energy.Read"))
    assert exc.value.reason == "missing_scope"


def test_tenant_is_required() -> None:
    with pytest.raises(ValueError):
        EntraTokenValidator(AUD, "", "Chat.Ask")
