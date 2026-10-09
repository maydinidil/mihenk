import httpx

from mihenk.api.security import TOKEN_HEADER, GuardConfig
from mihenk.api.server import create_app
from mihenk.app.launcher import ServerThread, bind_loopback, new_token


def test_server_thread_serves_and_stops() -> None:
    sock = bind_loopback()
    port = sock.getsockname()[1]
    token = new_token()
    server = ServerThread(create_app(GuardConfig(port=port, token=token), web_dist=None), sock)
    server.start()
    try:
        response = httpx.get(f"http://127.0.0.1:{port}/api/health", headers={TOKEN_HEADER: token})
        assert response.status_code == 200
    finally:
        server.stop()
    assert not server.running
