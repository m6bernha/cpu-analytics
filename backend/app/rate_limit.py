"""Per-IP sliding-window rate limiting for expensive public POST endpoints.

State is in-process, which matches the single-worker uvicorn deployment on
Render. If the app ever runs multiple workers or instances, move the
counters to a shared store before trusting the limits.

Disabled by setting RATE_LIMIT_ENABLED=0 (the test suite does this; see
backend/tests/conftest.py). Dedicated unit tests build their own app with
the middleware enabled: backend/tests/test_rate_limit.py.
"""

from __future__ import annotations

import os
import time
from collections import deque
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# (method, path) -> (max requests, window seconds). Scoped to the endpoints
# whose per-request compute is high enough to exhaust the free tier: scout
# fans out search + projection per roster entry (up to 500), manual
# trajectory accepts up to 200 entries per request.
DEFAULT_RULES: dict[tuple[str, str], tuple[int, float]] = {
    ("POST", "/api/scout/report"): (10, 60.0),
    ("POST", "/api/manual/trajectory"): (30, 60.0),
}

# Bucket-count cap so hostile IP churn cannot grow memory without bound.
MAX_BUCKETS = 10_000


def client_ip(request: Request) -> str:
    """Client IP as seen through Render's proxy.

    Render appends the real client IP as the LAST X-Forwarded-For entry;
    earlier entries arrive from the client and are spoofable, so only the
    last one is trusted. Without the header (local dev), use the socket
    peer.
    """
    xff = request.headers.get("x-forwarded-for", "")
    last = xff.rsplit(",", 1)[-1].strip()
    if last:
        return last
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        rules: dict[tuple[str, str], tuple[int, float]] | None = None,
        enabled: bool | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(app)
        self.rules = DEFAULT_RULES if rules is None else rules
        if enabled is None:
            enabled = os.environ.get("RATE_LIMIT_ENABLED", "1") == "1"
        self.enabled = enabled
        self.clock = clock
        self._max_window = max((w for _, w in self.rules.values()), default=0.0)
        self._hits: dict[tuple[str, str, str], deque[float]] = {}

    async def dispatch(self, request: Request, call_next):
        rule = self.rules.get((request.method, request.url.path)) if self.enabled else None
        if rule is None:
            return await call_next(request)
        limit, window = rule
        now = self.clock()
        key = (request.method, request.url.path, client_ip(request))
        hits = self._hits.get(key)
        if hits is None:
            self._prune(now)
            hits = self._hits[key] = deque()
        while hits and now - hits[0] >= window:
            hits.popleft()
        if len(hits) >= limit:
            retry_after = max(1, int(window - (now - hits[0])) + 1)
            return JSONResponse(
                {"error": "rate_limited", "retry_after_s": retry_after},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
        hits.append(now)
        return await call_next(request)

    def _prune(self, now: float) -> None:
        """Drop expired buckets; runs only when a new bucket is created."""
        if len(self._hits) < MAX_BUCKETS:
            return
        for key, hits in list(self._hits.items()):
            if not hits or now - hits[-1] >= self._max_window:
                del self._hits[key]
        # Pathological case: MAX_BUCKETS live IPs inside one window. Evict
        # arbitrary buckets rather than grow; eviction can only ever relax
        # limits, never block a legitimate first request.
        while len(self._hits) >= MAX_BUCKETS:
            self._hits.pop(next(iter(self._hits)))
