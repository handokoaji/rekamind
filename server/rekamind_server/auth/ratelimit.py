import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class RateLimiter:
    """Sliding window per client, in memory. Enough to stop credential-stuffing style hammering of
    the login endpoints on one server; it is not a substitute for a reverse proxy's limits."""

    def __init__(self, limit: int, window_seconds: float):
        self.limit, self.window = limit, window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        t, q = time.monotonic(), self._hits[key]
        while q and t - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            raise HTTPException(429, "Terlalu banyak percobaan. Coba lagi sebentar lagi.", headers={"Retry-After": str(int(self.window))})
        q.append(t)
