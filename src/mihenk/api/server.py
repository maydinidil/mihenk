"""The FastAPI application (design §5, §14)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from mihenk import __version__
from mihenk.api.routes import health, smoke
from mihenk.api.routes.smoke import SmokeSignal
from mihenk.api.security import GuardConfig, LocalOnlyGuard

_NOT_BUILT = (
    "<!doctype html><title>mihenk</title>"
    "<p>The screens are not built yet. Run <code>npm run build</code> in <code>web/</code>.</p>"
)


def create_app(
    config: GuardConfig, web_dist: Path | None, smoke_signal: SmokeSignal | None = None
) -> FastAPI:
    # docs_url, redoc_url and openapi_url are off: the docs pages load scripts from a CDN (§14).
    app = FastAPI(
        title="mihenk", version=__version__, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.include_router(health.router, prefix="/api")
    app.include_router(smoke.make_router(smoke_signal), prefix="/api")
    if web_dist is not None and (web_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="screens")
    else:

        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        def not_built() -> str:
            return _NOT_BUILT

    app.add_middleware(LocalOnlyGuard, config=config)
    return app
