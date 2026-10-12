import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from mihenk.api.security import TOKEN_HEADER, GuardConfig, LocalOnlyGuard

PORT = 51234
TOKEN = "test-token-0123456789abcdef0123456789"
BASE = f"http://127.0.0.1:{PORT}"
GOOD = {TOKEN_HEADER: TOKEN}


def make_client(root_path: str = "") -> TestClient:
    app = FastAPI()

    @app.get("/api/ping")
    def ping() -> dict[str, str]:
        return {"pong": "yes"}

    @app.get("/api")
    def bare_api() -> dict[str, str]:
        # A real route at the bare path, so a 200 would prove the guard let it through.
        return {"bare": "yes"}

    @app.post("/api/change")
    def change() -> dict[str, str]:
        return {"changed": "yes"}

    @app.get("/")
    def index() -> dict[str, str]:
        return {"page": "index"}

    @app.websocket("/ws")
    async def socket(websocket: WebSocket) -> None:
        # A route that accepts, so only the guard can be the reason the socket is refused.
        await websocket.accept()
        await websocket.close()

    app.add_middleware(LocalOnlyGuard, config=GuardConfig(port=PORT, token=TOKEN))
    return TestClient(app, base_url=BASE, root_path=root_path)


def test_api_get_with_token_passes() -> None:
    assert make_client().get("/api/ping", headers=GOOD).status_code == 200


def test_api_get_without_token_is_refused() -> None:
    response = make_client().get("/api/ping")
    assert response.status_code == 403
    assert response.text == "Refused: token"


def test_api_get_with_wrong_token_is_refused() -> None:
    response = make_client().get("/api/ping", headers={TOKEN_HEADER: "wrong"})
    assert response.status_code == 403
    assert response.text == "Refused: token"


def test_non_ascii_token_is_refused_without_crashing() -> None:
    response = make_client().get("/api/ping", headers={TOKEN_HEADER: b"t\xf6ken"})
    assert response.status_code == 403


@pytest.mark.parametrize(
    "host",
    [f"evil.example:{PORT}", "127.0.0.1", "127.0.0.1:80", f"127.0.0.2:{PORT}", ""],
)
def test_wrong_host_is_refused(host: str) -> None:
    response = make_client().get("/api/ping", headers={**GOOD, "host": host})
    assert response.status_code == 403
    assert response.text == "Refused: host"


def test_localhost_host_passes() -> None:
    response = make_client().get("/api/ping", headers={**GOOD, "host": f"localhost:{PORT}"})
    assert response.status_code == 200


def test_index_needs_no_token() -> None:
    assert make_client().get("/").status_code == 200


def test_post_without_origin_is_refused() -> None:
    response = make_client().post("/api/change", headers=GOOD)
    assert response.status_code == 403
    assert response.text == "Refused: origin"


def test_post_from_own_origin_passes() -> None:
    response = make_client().post("/api/change", headers={**GOOD, "origin": BASE})
    assert response.status_code == 200


def test_post_with_same_origin_fetch_site_but_no_origin_is_refused() -> None:
    # Design §14: a missing Origin is accepted only on GET and HEAD.
    headers = {**GOOD, "sec-fetch-site": "same-origin"}
    response = make_client().post("/api/change", headers=headers)
    assert response.status_code == 403
    assert response.text == "Refused: origin"


def test_origin_on_another_port_is_refused() -> None:
    headers = {**GOOD, "origin": "http://127.0.0.1:9999"}
    response = make_client().post("/api/change", headers=headers)
    assert response.status_code == 403
    assert response.text == "Refused: origin"


@pytest.mark.parametrize("site", ["same-site", "cross-site"])
def test_other_sites_are_refused(site: str) -> None:
    response = make_client().get("/api/ping", headers={**GOOD, "sec-fetch-site": site})
    assert response.status_code == 403
    assert response.text == "Refused: fetch-site"


def test_bare_api_path_needs_the_token() -> None:
    # "/api" is the API root just like "/api/...": no trailing slash must not skip the check.
    response = make_client().get("/api")
    assert response.status_code == 403
    assert response.text == "Refused: token"


def test_bare_api_path_with_token_passes() -> None:
    assert make_client().get("/api", headers=GOOD).status_code == 200


def test_paths_that_only_start_with_api_are_not_api_paths() -> None:
    # Pins today's boundary: only "/api" and "/api/..." are guarded by the token.
    assert make_client().get("/apiary").status_code == 404


def test_a_non_empty_root_path_is_refused() -> None:
    # The guard reads scope["path"] and the router strips root_path from it, so the two could
    # disagree about which route a request reaches.
    response = make_client(root_path="/prefix").get("/api/ping", headers=GOOD)
    assert response.status_code == 403
    assert response.text == "Refused: root-path"


def test_an_empty_root_path_passes() -> None:
    assert make_client(root_path="").get("/api/ping", headers=GOOD).status_code == 200


def test_head_on_the_api_needs_the_token() -> None:
    response = make_client().head("/api/")
    assert response.status_code == 403
    assert response.text == ""  # a HEAD answer has no body, whatever the guard says


def test_head_on_an_api_route_with_the_token_passes_the_guard() -> None:
    # FastAPI's GET routes answer HEAD with 405; what matters here is that the guard is not
    # the one refusing.
    assert make_client().head("/api/ping", headers=GOOD).status_code != 403


def test_options_on_the_api_without_origin_is_refused() -> None:
    # OPTIONS is not GET or HEAD, so a missing Origin is refused (design 14).
    response = make_client().options("/api/ping", headers=GOOD)
    assert response.status_code == 403
    assert response.text == "Refused: origin"


def test_options_on_the_api_from_own_origin_passes_the_guard() -> None:
    # The guard lets it through; the app has no CORS middleware, so the router answers 405.
    response = make_client().options("/api/ping", headers={**GOOD, "origin": BASE})
    assert response.status_code == 405


def test_options_on_the_api_without_token_is_refused() -> None:
    response = make_client().options("/api/", headers={"origin": BASE})
    assert response.status_code == 403
    assert response.text == "Refused: token"


def test_post_with_a_null_origin_is_refused() -> None:
    # Sandboxed iframes and redirects send "Origin: null"; it is not the app's own origin.
    response = make_client().post("/api/change", headers={**GOOD, "origin": "null"})
    assert response.status_code == 403
    assert response.text == "Refused: origin"


def test_get_with_a_foreign_origin_is_refused() -> None:
    # Stricter than design 14, which names Origin only for state-changing requests: any request
    # that carries an Origin must carry the app's own.
    response = make_client().get("/api/ping", headers={**GOOD, "origin": "https://evil.example"})
    assert response.status_code == 403
    assert response.text == "Refused: origin"


def test_sec_fetch_site_none_passes() -> None:
    # "none" is a navigation the user started themselves (typing the address, a bookmark).
    response = make_client().get("/api/ping", headers={**GOOD, "sec-fetch-site": "none"})
    assert response.status_code == 200


def test_websocket_is_refused() -> None:
    with (
        pytest.raises(WebSocketDisconnect) as refused,
        make_client().websocket_connect("/ws"),
    ):
        pass
    assert refused.value.code == 1008


def test_config_accepts_the_shortest_valid_token_and_the_port_limits() -> None:
    assert GuardConfig(port=1, token="a" * 32).port == 1
    assert GuardConfig(port=65535, token="a" * 32).port == 65535


@pytest.mark.parametrize("token", ["", "short", "a" * 31])
def test_config_rejects_a_token_under_32_characters(token: str) -> None:
    with pytest.raises(ValueError, match="at least 32 characters"):
        GuardConfig(port=PORT, token=token)


def test_config_rejects_a_non_ascii_token() -> None:
    with pytest.raises(ValueError, match="ASCII"):
        GuardConfig(port=PORT, token="töken-" + "a" * 32)


@pytest.mark.parametrize("port", [-1, 0, 65536])
def test_config_rejects_a_port_outside_1_to_65535(port: int) -> None:
    with pytest.raises(ValueError, match="port"):
        GuardConfig(port=port, token=TOKEN)
