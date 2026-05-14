"""In-memory rate limiting middleware for MVP.

For production, swap to Redis-based rate limiting using the same interface.
"""

import time
from collections import defaultdict

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware


class RateLimiter:
    """Simple in-memory sliding-window rate limiter.

    Tracks request timestamps per client IP. When the number of requests
    within the window exceeds *max_requests*, returns HTTP 429.

    Note:
        This is per-process — each uvicorn worker has its own counter.
        Acceptable for MVP; production should use Redis.
    """

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clients: dict[str, list[float]] = defaultdict(list)

    def _cleanup(self, key: str, now: float) -> None:
        """Remove timestamps outside the sliding window."""
        cutoff = now - self.window_seconds
        self._clients[key] = [t for t in self._clients[key] if t > cutoff]

    async def __call__(self, request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        now = time.time()
        self._cleanup(key, now)

        if len(self._clients[key]) >= self.max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="请求过于频繁，请稍后再试",
            )

        self._clients[key].append(now)


rate_limiter = RateLimiter(max_requests=60, window_seconds=60)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Starlette middleware wrapping the RateLimiter callable."""

    async def dispatch(self, request: Request, call_next):
        await rate_limiter(request)
        response = await call_next(request)
        return response
