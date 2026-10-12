"""The local-only guard that runs before every route (design §14).

Three checks: the Host header names this server exactly, port included; a state-changing
request comes from this app's own origin; every /api request (the bare path included) carries
the token created at launch. A request whose ASGI scope has a root_path is refused too, because
the guard and the router would read different paths. Anything else gets a 403 before any route
runs. CORS is not a defence here: it hides answers from other sites but still runs their
requests.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

TOKEN_HEADER = "x-mihenk-token"  # noqa: S105 - a header name, not a secret
_SAFE_METHODS = frozenset({"GET", "HEAD"})
_TRUSTED_FETCH_SITES = frozenset({"same-origin", "none"})


# Sent on every response, refusals and static files included. The built screens load only their
# own scripts and styles and talk only to this server, so nothing outside 'self' is allowed
# (a tiny data: image is for the empty favicon). Captured pages are never rendered here (§14).
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
    "form-action 'self'"
)

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


def _is_api_path(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def refusal_reason(
    config: GuardConfig, method: str, path: str, headers: Headers, root_path: str = ""
) -> str | None:
    """Why a request must be refused, or None when it may pass."""
    if headers.get("host", "") not in config.allowed_hosts:
        return "host"
    if root_path:
        # The router strips root_path from the path before it matches a route, the guard does
        # not, so the two could disagree about what is being asked for. This app never has one.
        return "root-path"
    origin = headers.get("origin")
    if origin is not None and origin not in config.allowed_origins:
        return "origin"
    fetch_site = headers.get("sec-fetch-site")
    if fetch_site is not None and fetch_site not in _TRUSTED_FETCH_SITES:
        return "fetch-site"
    if method not in _SAFE_METHODS and origin is None:
        return "origin"
    if _is_api_path(path):
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
        reason = refusal_reason(
            self.config, scope["method"], scope["path"], headers, scope.get("root_path", "")
        )
        if reason is not None:
            response = PlainTextResponse(f"Refused: {reason}", status_code=403)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class ContentSecurityPolicy:
    """Adds the Content-Security-Policy header to every HTTP response the app below sends.

    Added outside the guard, so the guard's own refusals carry it too.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_policy(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
            await send(message)

        await self.app(scope, receive, send_with_policy)
