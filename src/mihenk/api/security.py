"""The local-only guard that runs before every route (design §14).

Three checks: the Host header names this server exactly, port included; a state-changing
request comes from this app's own origin; every /api/ request carries the token created at
launch. Anything else gets a 403 before any route runs. CORS is not a defence here: it hides
answers from other sites but still runs their requests.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

TOKEN_HEADER = "x-mihenk-token"  # noqa: S105 - a header name, not a secret
_SAFE_METHODS = frozenset({"GET", "HEAD"})
_TRUSTED_FETCH_SITES = frozenset({"same-origin", "none"})


_MIN_TOKEN_LENGTH = 32


@dataclass(frozen=True)
class GuardConfig:
    port: int
    token: str

    def __post_init__(self) -> None:
        # An empty or short token would weaken the check, and a non-ASCII one would crash it.
        if not 1 <= self.port <= 65535:
            raise ValueError(f"port must be from 1 to 65535, got {self.port}")
        if not self.token.isascii():
            raise ValueError("token must be ASCII")
        if len(self.token) < _MIN_TOKEN_LENGTH:
            raise ValueError(f"token must be at least {_MIN_TOKEN_LENGTH} characters")

    @property
    def allowed_hosts(self) -> frozenset[str]:
        return frozenset({f"127.0.0.1:{self.port}", f"localhost:{self.port}"})

    @property
    def allowed_origins(self) -> frozenset[str]:
        return frozenset({f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"})


def refusal_reason(config: GuardConfig, method: str, path: str, headers: Headers) -> str | None:
    """Why a request must be refused, or None when it may pass."""
    if headers.get("host", "") not in config.allowed_hosts:
        return "host"
    origin = headers.get("origin")
    if origin is not None and origin not in config.allowed_origins:
        return "origin"
    fetch_site = headers.get("sec-fetch-site")
    if fetch_site is not None and fetch_site not in _TRUSTED_FETCH_SITES:
        return "fetch-site"
    if method not in _SAFE_METHODS and origin is None:
        return "origin"
    if path.startswith("/api/"):
        supplied = headers.get(TOKEN_HEADER, "").encode("latin-1")
        if not hmac.compare_digest(supplied, config.token.encode("ascii")):
            return "token"
    return None


class LocalOnlyGuard:
    def __init__(self, app: ASGIApp, config: GuardConfig) -> None:
        self.app = app
        self.config = config

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            await receive()
            await send({"type": "websocket.close", "code": 1008})
            return
        headers = Headers(scope=scope)
        reason = refusal_reason(self.config, scope["method"], scope["path"], headers)
        if reason is not None:
            response = PlainTextResponse(f"Refused: {reason}", status_code=403)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
