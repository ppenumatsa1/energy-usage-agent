"""Sliding-window limiter per user, in memory (per replica; fine for the POC)."""

import math
import time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self, per_minute: int, clock=time.monotonic) -> None:  # type: ignore[no-untyped-def]
        self._limit, self._clock = per_minute, clock
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str) -> int | None:
        now = self._clock()
        q = self._hits.setdefault(key, deque())
        while q and q[0] <= now - 60:
            q.popleft()
        if len(q) >= self._limit:
            return max(1, math.ceil(q[0] + 60 - now))
        q.append(now)
        return None
