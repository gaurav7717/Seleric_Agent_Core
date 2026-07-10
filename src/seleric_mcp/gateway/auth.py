"""Shared service-token auth for the streamable-http transport (MVP; OAuth 2.1
deferred). stdio trusts the local process and skips this entirely."""

from __future__ import annotations

import hmac

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class BearerTokenMiddleware:
    def __init__(self, app: ASGIApp, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        auth = request.headers.get("authorization", "")
        supplied = auth.removeprefix("Bearer ").strip()
        if not self.token or not hmac.compare_digest(supplied, self.token):
            response = JSONResponse({"error": "unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
