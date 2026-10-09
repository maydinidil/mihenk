import logging
import sys

import httpx
import pytest

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


def test_server_thread_runs_without_console_and_logs_to_root(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # The windowed build (console=False) has no stdout or stderr, and mihenk.log hangs off the
    # root logger, so the server must start without either stream and its errors must propagate.
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    sock = bind_loopback()
    port = sock.getsockname()[1]
    server = ServerThread(
        create_app(GuardConfig(port=port, token=new_token()), web_dist=None), sock
    )
    server.start()
    try:
        logging.getLogger("uvicorn.error").warning("server error probe")
    finally:
        server.stop()
    assert not server.running
    assert "server error probe" in caplog.text
