from pathlib import Path

from fastapi.testclient import TestClient

from mihenk import __version__
from mihenk.api.routes.smoke import SmokeSignal
from mihenk.api.security import TOKEN_HEADER, GuardConfig
from mihenk.api.server import create_app

PORT = 51235
TOKEN = "server-test-token-0123456789"
BASE = f"http://127.0.0.1:{PORT}"
GOOD = {TOKEN_HEADER: TOKEN, "origin": BASE}


def client(web_dist: Path | None = None, smoke: SmokeSignal | None = None) -> TestClient:
    app = create_app(GuardConfig(port=PORT, token=TOKEN), web_dist=web_dist, smoke_signal=smoke)
    return TestClient(app, base_url=BASE)


def test_health() -> None:
    response = client().get("/api/health", headers=GOOD)
    assert response.json() == {"status": "ok", "version": __version__}


def test_docs_and_openapi_routes_are_off() -> None:
    for path in ("/docs", "/redoc", "/openapi.json", "/api/openapi.json"):
        assert client().get(path, headers=GOOD).status_code == 404


def test_unbuilt_screens_show_a_hint() -> None:
    response = client(web_dist=None).get("/")
    assert response.status_code == 200
    assert "npm run build" in response.text


def test_built_screens_are_served(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<!doctype html><title>mihenk</title>", encoding="utf-8")
    response = client(web_dist=tmp_path).get("/")
    assert "<title>mihenk</title>" in response.text


def test_smoke_route_is_404_outside_smoke_mode() -> None:
    assert client().post("/api/smoke/ok", headers=GOOD).status_code == 404


def test_smoke_route_sets_the_signal() -> None:
    signal = SmokeSignal()
    response = client(smoke=signal).post("/api/smoke/ok", headers=GOOD)
    assert response.json() == {"received": True}
    assert signal.event.is_set()


def test_openapi_schema_is_still_buildable_in_process() -> None:
    app = create_app(GuardConfig(port=PORT, token=TOKEN), web_dist=None)
    schema = app.openapi()
    assert "/api/health" in schema["paths"]
