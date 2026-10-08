import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from mihenk.api.security import TOKEN_HEADER, GuardConfig, LocalOnlyGuard

PORT = 51234
TOKEN = "test-token-0123456789abcdef0123456789"
BASE = f"http://127.0.0.1:{PORT}"
GOOD = {TOKEN_HEADER: TOKEN}


def make_client() -> TestClient:
    app = FastAPI()

    @app.get("/api/ping")
    def ping() -> dict[str, str]:
        return {"pong": "yes"}

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
    return TestClient(app, base_url=BASE)


def test_api_get_with_token_passes() -> None:
    assert make_client().get("/api/ping", headers=GOOD).status_code == 200


def test_api_get_without_token_is_refused() -> None:
    response = make_client().get("/api/ping")
    assert response.status_code == 403
    assert response.text == "Refused: token"


def test_api_get_with_wrong_token_is_refused() -> None:
    response = make_client().get("/api/ping", headers={TOKEN_HEADER: "wrong"})
    assert response.status_code == 403


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
    assert make_client().post("/api/change", headers=headers).status_code == 403


@pytest.mark.parametrize("site", ["same-site", "cross-site"])
def test_other_sites_are_refused(site: str) -> None:
    response = make_client().get("/api/ping", headers={**GOOD, "sec-fetch-site": site})
    assert response.status_code == 403
    assert response.text == "Refused: fetch-site"


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
