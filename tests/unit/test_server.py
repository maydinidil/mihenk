from pathlib import Path

from fastapi.testclient import TestClient

from mihenk import __version__
from mihenk.api.routes.smoke import SmokeSignal
from mihenk.api.security import TOKEN_HEADER, GuardConfig
from mihenk.api.server import create_app

PORT = 51235
TOKEN = "server-test-token-0123456789abcdef"
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


def test_app_refuses_an_api_request_without_the_token() -> None:
    response = client().get("/api/health")
    assert response.status_code == 403
    assert response.text == "Refused: token"


def test_app_refuses_a_post_without_origin() -> None:
    response = client().post("/api/smoke/ok", headers={TOKEN_HEADER: TOKEN})
    assert response.status_code == 403
    assert response.text == "Refused: origin"


def test_app_refuses_a_wrong_host_on_the_static_mount(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<!doctype html><title>mihenk</title>", encoding="utf-8")
    response = client(web_dist=tmp_path).get("/", headers={"host": f"evil.example:{PORT}"})
    assert response.status_code == 403
    assert response.text == "Refused: host"


CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
    "form-action 'self'"
)


def test_csp_is_on_the_unbuilt_screens_hint() -> None:
    response = client(web_dist=None).get("/")
    assert response.status_code == 200
    assert response.headers["content-security-policy"] == CSP


def test_csp_is_on_the_built_screens_and_their_files(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<!doctype html><title>mihenk</title>", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log(1)", encoding="utf-8")
    page = client(web_dist=tmp_path)
    assert page.get("/").headers["content-security-policy"] == CSP
    asset = page.get("/app.js")
    assert asset.status_code == 200
    assert asset.headers["content-security-policy"] == CSP
    missing = page.get("/nope.js")
    assert missing.status_code == 404
    assert missing.headers["content-security-policy"] == CSP


def test_csp_is_on_an_api_route() -> None:
    response = client().get("/api/health", headers=GOOD)
    assert response.status_code == 200
    assert response.headers["content-security-policy"] == CSP


def test_csp_is_on_a_refused_request() -> None:
    response = client().get("/api/health")
    assert response.status_code == 403
    assert response.headers["content-security-policy"] == CSP
    wrong_host = client().get("/", headers={"host": f"evil.example:{PORT}"})
    assert wrong_host.status_code == 403
    assert wrong_host.headers["content-security-policy"] == CSP


def test_csp_is_on_an_unhandled_error() -> None:
    app = create_app(GuardConfig(port=PORT, token=TOKEN), web_dist=None)

    def boom() -> None:
        raise RuntimeError("probe")

    app.add_api_route("/api/boom", boom)
    response = TestClient(app, base_url=BASE, raise_server_exceptions=False).get(
        "/api/boom", headers=GOOD
    )
    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert response.headers["content-security-policy"] == CSP


def test_index_html_declares_an_inline_icon() -> None:
    # Without a <link rel="icon">, the browser asks for /favicon.ico, gets a 404 and logs an error.
    # "data:," is an empty icon, and the policy's img-src allows data: for it.
    index = Path(__file__).resolve().parents[2] / "web" / "index.html"
    assert '<link rel="icon" href="data:," />' in index.read_text(encoding="utf-8")
