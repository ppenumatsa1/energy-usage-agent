"""Synthetic local users. All IDs are made up and exist only in local seed data."""

import time
from dataclasses import dataclass

import jwt

from .validators import DEV_ISSUER

TENANT_A = "0000000a-0000-4000-8000-000000000000"
TENANT_B = "0000000b-0000-4000-8000-000000000000"


@dataclass(frozen=True)
class DevUser:
    id: str
    label: str
    tid: str
    oid: str
    name: str


DEV_USERS: dict[str, DevUser] = {
    u.id: u
    for u in (
        DevUser(
            "a1",
            "Tenant A · User 1 (Customer 1)",
            TENANT_A,
            "00000001-0000-4000-8000-0000000000a1",
            "User A1",
        ),
        DevUser(
            "a2",
            "Tenant A · User 2 (Customer 2)",
            TENANT_A,
            "00000002-0000-4000-8000-0000000000a2",
            "User A2",
        ),
        DevUser(
            "b1",
            "Tenant B · User 1 (Customer 3)",
            TENANT_B,
            "00000003-0000-4000-8000-0000000000b1",
            "User B1",
        ),
        DevUser(
            "x1", "Tenant A · Not onboarded", TENANT_A, "00000009-0000-4000-8000-0000000000f1", "User X1"
        ),
    )
}


def mint_dev_token(
    secret: str, audience: str, scope: str, tid: str, oid: str, name: str | None = None, ttl: int = 3600
) -> str:
    now = int(time.time())
    claims = {
        "iss": DEV_ISSUER,
        "aud": audience,
        "iat": now,
        "nbf": now,
        "exp": now + ttl,
        "tid": tid,
        "oid": oid,
        "scp": scope,
        "name": name,
    }
    return jwt.encode(claims, secret, algorithm="HS256")
