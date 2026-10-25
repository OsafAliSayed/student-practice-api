"""In-memory sliding-window rate limiter: a deque of timestamps per key label."""

import math
import time
from collections import deque
from dataclasses import dataclass

LIMIT = 30
WINDOW_SECONDS = 60.0


@dataclass
class Decision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int | None = None


class SlidingWindowLimiter:
    def __init__(self, limit: int = LIMIT, window: float = WINDOW_SECONDS, clock=time.monotonic):
        self.limit = limit
        self.window = window
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str) -> Decision:
        now = self.clock()
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            # Rejected requests are not recorded, so the wait is exactly until the oldest expires.
            retry_after = max(1, math.ceil(hits[0] + self.window - now))
            return Decision(False, self.limit, 0, retry_after)
        hits.append(now)
        return Decision(True, self.limit, self.limit - len(hits))
