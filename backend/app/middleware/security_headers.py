"""
Olympus Engine v9 — Security Headers Middleware (ASGI-native)
Adds hardened response headers, removes server fingerprinting.
"""
from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

INJECT_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (
        b"permissions-policy",
        b"camera=(self), microphone=(self), geolocation=(), payment=(), usb=()",
    ),
]

REMOVE_HEADERS = {b"server", b"x-powered-by"}


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() not in REMOVE_HEADERS
                ]
                headers.extend(INJECT_HEADERS)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)
# VERIFIED: ASGI-native, adds X-Content-Type-Options/X-Frame-Options/Referrer-Policy/Permissions-Policy, removes Server+X-Powered-By.
