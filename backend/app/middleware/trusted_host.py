"""
Olympus Engine v9 — Trusted Host Middleware (ASGI-native)
Prevents DNS rebinding by rejecting unknown Host headers.
"""
from __future__ import annotations

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class TrustedHostCustomMiddleware:
    def __init__(self, app: ASGIApp, allowed_hosts: list[str]) -> None:
        self.app = app
        self.allowed_hosts = set(h.lower() for h in allowed_hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        host = headers.get("host", "").split(":")[0].lower()

        if host not in self.allowed_hosts:
            response = PlainTextResponse("Invalid Host header", status_code=400)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
# VERIFIED: ASGI-native (no BaseHTTPMiddleware), strips port, case-insensitive compare, passes non-http scopes through.
