"""Per-API-key rate limiter — fixed-window counters in Redis.

Per design §Component 9: three fixed-window counters per request
keyed by ``(api_key_id, window_label, window_start_epoch)`` backed by
Redis. A single Lua script atomically ``INCR``s all three counters and
sets ``EXPIRE`` only on the first hit of each window so we make exactly
one round trip per request.

Authentication path coupling
----------------------------

JWT-authenticated requests bypass the per-key counter path: their
RBAC role on each endpoint is what governs them, and an
external-facing IP-based limiter (out of scope here) sits in front
for anonymous abuse. API-key-authenticated requests pass through
the counter path; if Redis is unreachable, requests are rejected
with HTTP 503 fail-closed per Req 6.7.

Identity choice and trade-off
-----------------------------

The middleware uses the API key's ``key_prefix`` (the first eleven
characters of the plaintext, e.g. ``sk_live_ab``) as the rate-limit
identity. Resolving to the canonical row id would require a database
round trip in the middleware, which contradicts the "single Redis
round trip per request" budget. As a consequence, this tier does
**not** honour ``ApiKey.rate_limit_overrides``: only the platform
defaults from settings are applied. A follow-up can add a Redis-cached
overrides hash if per-key overrides at the middleware tier are needed.

Headers and audit
-----------------

* On every successful response: ``X-RateLimit-Limit`` (per-minute
  quota), ``X-RateLimit-Remaining``, ``X-RateLimit-Reset`` (Unix
  timestamp at which the minute window resets).
* On 429: ``Retry-After`` set to ``min(reset(w) - now)`` over
  exceeded windows; an ``rate_limit.rejected`` audit row is emitted.
* On Redis outage: HTTP 503 with body
  ``{"error": "rate_limiter.backend_unavailable"}``; a
  ``rate_limiter.backend_unavailable`` audit row is emitted.
"""

from __future__ import annotations

import logging
import time
from typing import Optional, Tuple

import redis.asyncio as aioredis
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from ..config import settings

logger = logging.getLogger(__name__)


# Window labels and their durations in seconds.
_WINDOW_DURATIONS = {
    "minute": 60,
    "hour": 3600,
    "day": 86400,
}

# TTL pad: ensure keys outlive the window slightly to absorb clock
# skew between Redis and the app server (Req 6.1).
_WINDOW_TTLS = {
    "minute": 70,
    "hour": 4000,
    "day": 90000,
}


# Lua script: atomically INCR each of three keys, set EXPIRE only when
# the new value is 1 (first hit in the window). Returns the three new
# counts as a list.
#
# KEYS[1..3]: minute, hour, day keys
# ARGV[1..3]: corresponding TTLs
_LUA_INCR_THREE = """
local m = redis.call('INCR', KEYS[1])
if m == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
local h = redis.call('INCR', KEYS[2])
if h == 1 then redis.call('EXPIRE', KEYS[2], ARGV[2]) end
local d = redis.call('INCR', KEYS[3])
if d == 1 then redis.call('EXPIRE', KEYS[3], ARGV[3]) end
return {m, h, d}
"""


def _window_start_epoch(now: int, duration: int) -> int:
    """Return the start of the current fixed window (truncated).

    Args:
        now: Current Unix timestamp in seconds.
        duration: Window length in seconds.

    Returns:
        The Unix timestamp at which the window containing ``now``
        began.
    """
    return (now // duration) * duration


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-API-key fixed-window rate limiter.

    Mounted on the FastAPI app via ``app.add_middleware(...)``. The
    middleware probes the request headers for an API-key plaintext
    (``Authorization: Bearer sk_...`` or ``X-API-Key: sk_...``).
    JWT-only requests pass through without any counter activity. For
    API-key requests, a single Redis Lua call increments three
    fixed-window counters; the request either continues with
    rate-limit response headers attached or is rejected 429 with a
    ``Retry-After`` header.

    A Redis connection error or socket timeout fails closed: the
    request is rejected 503 with machine code
    ``rate_limiter.backend_unavailable`` and an audit row is emitted.
    """

    def __init__(self, app):
        """Initialize the middleware with a lazily-built Redis client."""
        super().__init__(app)
        self._redis: Optional[aioredis.Redis] = None

    async def _get_redis(self) -> aioredis.Redis:
        """Return the shared async Redis client, building it on first use.

        The client is configured with a 1-second socket timeout to
        keep middleware latency bounded under Redis stress; that
        timeout is what triggers the fail-closed branch in
        :meth:`dispatch`.
        """
        if self._redis is None:
            self._redis = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_timeout=1.0,
                socket_connect_timeout=1.0,
            )
        return self._redis

    @staticmethod
    def _resolve_api_key_identity(request: Request) -> Optional[Tuple[str, dict]]:
        """Extract an API-key identity from request headers, or None.

        The middleware runs before FastAPI dependency injection and
        cannot resolve the canonical ``ApiKey`` row without a database
        round trip. Instead, it uses the 11-character ``key_prefix``
        of the plaintext as the rate-limit identity (see module
        docstring for the trade-off discussion). Per-key overrides
        are not honoured here.

        Args:
            request: The inbound FastAPI/Starlette request.

        Returns:
            ``(key_prefix, overrides_dict)`` for an API-key request,
            or ``None`` for a JWT-only or unauthenticated request.
            ``overrides_dict`` is always empty at this tier.
        """
        token: Optional[str] = None

        auth = request.headers.get("Authorization") or request.headers.get(
            "authorization"
        )
        if auth:
            scheme, _, value = auth.partition(" ")
            value = value.strip()
            if scheme.lower() == "bearer" and value.startswith("sk_"):
                token = value

        if token is None:
            x_api_key = request.headers.get("X-API-Key") or request.headers.get(
                "x-api-key"
            )
            if x_api_key and x_api_key.startswith("sk_"):
                token = x_api_key

        if token is None:
            return None

        return (token[:11], {})

    async def dispatch(self, request: Request, call_next) -> Response:
        """Apply the per-API-key rate limit to the request.

        See class docstring for the high-level flow.
        """
        identity = self._resolve_api_key_identity(request)
        if identity is None:
            # JWT-only or anonymous: skip the per-key counter path.
            return await call_next(request)

        api_key_id, _overrides = identity
        now = int(time.time())

        windows = ("minute", "hour", "day")
        keys = []
        ttls = []
        for w in windows:
            duration = _WINDOW_DURATIONS[w]
            ws = _window_start_epoch(now, duration)
            keys.append(f"ratelimit:{api_key_id}:{w[0]}:{ws}")
            ttls.append(_WINDOW_TTLS[w])

        # Default platform quotas only at this tier (see module docstring).
        limits = {
            "minute": settings.rate_limit_default_per_minute,
            "hour": settings.rate_limit_default_per_hour,
            "day": settings.rate_limit_default_per_day,
        }

        try:
            redis_client = await self._get_redis()
            counts = await redis_client.eval(
                _LUA_INCR_THREE, 3, *keys, *ttls
            )
        except Exception as exc:  # noqa: BLE001 — Redis failure must fail closed
            logger.warning("Rate limiter Redis unavailable: %s", exc)
            await self._emit_backend_unavailable_audit(api_key_id, request)
            return JSONResponse(
                status_code=503,
                content={"error": "rate_limiter.backend_unavailable"},
            )

        try:
            counts_int = [int(c) for c in counts]
        except (ValueError, TypeError):
            logger.warning("Unexpected counter shape from Redis: %r", counts)
            counts_int = [0, 0, 0]

        c_minute, c_hour, c_day = counts_int
        c_by_window = {"minute": c_minute, "hour": c_hour, "day": c_day}

        exceeded = [w for w in windows if c_by_window[w] > limits[w]]
        if exceeded:
            reset_seconds = []
            for w in exceeded:
                duration = _WINDOW_DURATIONS[w]
                ws = _window_start_epoch(now, duration)
                next_reset = ws + duration
                reset_seconds.append(next_reset - now)
            retry_after = max(1, min(reset_seconds))
            await self._emit_rate_limit_rejected_audit(
                api_key_id, request, exceeded[0]
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limited",
                    "details": {"window": exceeded[0]},
                },
                headers={"Retry-After": str(retry_after)},
            )

        # Within quota: forward and decorate the response.
        response = await call_next(request)

        minute_duration = _WINDOW_DURATIONS["minute"]
        minute_ws = _window_start_epoch(now, minute_duration)
        minute_reset = minute_ws + minute_duration
        response.headers["X-RateLimit-Limit"] = str(limits["minute"])
        response.headers["X-RateLimit-Remaining"] = str(
            max(0, limits["minute"] - c_minute)
        )
        response.headers["X-RateLimit-Reset"] = str(minute_reset)
        return response

    async def _emit_rate_limit_rejected_audit(
        self,
        api_key_id: str,
        request: Request,
        window: str,
    ) -> None:
        """Emit a ``rate_limit.rejected`` audit row.

        Uses a fresh database session so the audit write does not
        depend on any per-request session that the route handler
        might have opened. Audit-write failures are logged and
        swallowed — they must never mask the original 429.
        """
        try:
            from ..core.audit import log_audit
            from ..database import async_session

            async with async_session() as db:
                await log_audit(
                    db,
                    action="rate_limit.rejected",
                    user_id=None,
                    resource_type="api_key",
                    resource_id=None,
                    details={
                        "key_prefix": api_key_id,
                        "window": window,
                        "method": request.method,
                        "path": request.url.path,
                    },
                    request=request,
                )
                await db.commit()
        except Exception:  # noqa: BLE001 — audit write must not raise
            logger.exception("Failed to emit rate_limit.rejected audit")

    async def _emit_backend_unavailable_audit(
        self,
        api_key_id: str,
        request: Request,
    ) -> None:
        """Emit a ``rate_limiter.backend_unavailable`` audit row.

        Used on Redis outage. Audit-write failures are logged and
        swallowed — they must never mask the 503 returned to the
        caller.
        """
        try:
            from ..core.audit import log_audit
            from ..database import async_session

            async with async_session() as db:
                await log_audit(
                    db,
                    action="rate_limiter.backend_unavailable",
                    user_id=None,
                    resource_type="system",
                    resource_id=None,
                    details={
                        "key_prefix": api_key_id,
                        "method": request.method,
                        "path": request.url.path,
                    },
                    request=request,
                )
                await db.commit()
        except Exception:  # noqa: BLE001 — audit write must not raise
            logger.exception(
                "Failed to emit rate_limiter.backend_unavailable audit"
            )
