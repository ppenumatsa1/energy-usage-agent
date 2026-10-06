from dataclasses import dataclass, field


class AuthError(Exception):
    """Token missing or invalid. `reason` is safe to log; it never contains the token."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Principal:
    """The signed-in user. The customer is NOT here: only the energy-service maps (tid, oid) to a customer."""

    tid: str
    oid: str
    name: str | None = None
    scopes: frozenset[str] = frozenset()
    token: str = field(default="", repr=False, compare=False)

    @property
    def key(self) -> str:
        return f"{self.tid}:{self.oid}"
