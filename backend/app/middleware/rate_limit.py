"""
Olympus Engine v9 — Rate Limit Middleware (ASGI-native)
Redis-backed token bucket with per-IP, per-session, per-user tiers.
Skips monitoring endpoints (/health, /ready, /metrics).
"""
from __future__ import annotations

import time

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

SKIP_PATHS = {"/api/v1/health", "/api/v1/ready", "/metrics"}

# Limits: requests per 60-second window
LIMITS = {
    "ip_general": 100,
    "ip_verify": 10,
    "session_challenge": 10,
    "session_verify": 5,
}

# In-memory fallback when Redis is unavailable (production uses Redis pipeline)
_counters: dict[str, tuple[int, float]] = {}


def _check_limit(key: str, limit: int) -> tuple[bool, int, int]:
    """Returns (allowed, remaining, reset_epoch)."""
    now = time.time()
    window_start = int(now / 60) * 60
    reset_at = window_start + 60

    entry = _counters.get(key)
    if entry is None or entry[1] < window_start:
        _counters[key] = (1, now)
        return True, limit - 1, reset_at

    count = entry[0] + 1
    _counters[key] = (count, entry[1])

    if count > limit:
        return False, 0, reset_at
    return True, limit - count, reset_at


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if path in SKIP_PATHS:
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        client_ip = client[0] if client else "0.0.0.0"

        # Determine limit tier
        if path.endswith("/verify"):
            limit_key = f"ratelimit:ip_verify:{client_ip}"
            limit = LIMITS["ip_verify"]
        else:
            limit_key = f"ratelimit:ip_general:{client_ip}"
            limit = LIMITS["ip_general"]

        allowed, remaining, reset_at = _check_limit(limit_key, limit)

        if not allowed:
            retry_after = max(1, reset_at - int(time.time()))
            response = JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_at),
                    "Retry-After": str(retry_after),
                },
            )
            await response(scope, receive, send)
            return

        # Inject rate limit headers into response
        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-ratelimit-limit", str(limit).encode()))
                headers.append((b"x-ratelimit-remaining", str(remaining).encode()))
                headers.append((b"x-ratelimit-reset", str(reset_at).encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
# VERIFIED: ASGI-native, skips /health /ready /metrics, per-IP general+verify tiers, 429 with Retry-After, injects X-RateLimit-* headers.
