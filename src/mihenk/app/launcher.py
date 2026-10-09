"""Starts mihenk: data folder, local server, window (design §5).

The window owns the main thread, as pywebview requires. The server runs under uvicorn in a
background thread and is told to exit when the window closes.
"""

from __future__ import annotations

import argparse
import logging
import secrets
import socket
import threading
import time
import webbrowser
from collections.abc import Sequence
from importlib import resources
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from mihenk.api.routes.smoke import SmokeSignal
from mihenk.api.security import GuardConfig
from mihenk.api.server import create_app
from mihenk.app.paths import default_data_dir, logs_dir

log = logging.getLogger(__name__)


class ServerStartError(RuntimeError):
    pass


def new_token() -> str:
    return secrets.token_urlsafe(32)


def bind_loopback() -> socket.socket:
    """A socket on 127.0.0.1 with a free port, handed to uvicorn so no other process can take it."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    return sock


def launch_url(port: int, token: str, *, smoke: bool = False) -> str:
    fragment = f"token={token}" + ("&smoke=1" if smoke else "")
    return f"http://127.0.0.1:{port}/#{fragment}"


def bundled_web_dist() -> Path:
    return Path(str(resources.files("mihenk") / "web_dist"))


class ServerThread:
    def __init__(self, app: FastAPI, sock: socket.socket) -> None:
        # proxy_headers=False: uvicorn otherwise trusts X-Forwarded-* from 127.0.0.1, and every
        # caller of this server is on 127.0.0.1, so any local program could set them.
        # log_config=None: uvicorn's default config needs a console (the windowed build has
        # none) and stops its loggers propagating, so server errors would miss mihenk.log.
        config = uvicorn.Config(
            app, log_level="warning", access_log=False, proxy_headers=False, log_config=None
        )
        self._server = uvicorn.Server(config)
        self._sock = sock
        self._thread = threading.Thread(target=self._run, name="mihenk-server", daemon=True)

    def _run(self) -> None:
        self._server.run(sockets=[self._sock])

    def start(self, timeout_s: float = 10.0) -> None:
        self._thread.start()
        deadline = time.monotonic() + timeout_s
        while not self._server.started:
            if not self._thread.is_alive():
                raise ServerStartError("the local server stopped while starting")
            if time.monotonic() > deadline:
                raise ServerStartError("the local server did not start in time")
            time.sleep(0.02)

    def stop(self, timeout_s: float = 10.0) -> None:
        self._server.should_exit = True
        self._thread.join(timeout_s)
        self._sock.close()

    @property
    def running(self) -> bool:
        return self._thread.is_alive()


def run_window(url: str) -> None:
    import webview

    webview.create_window("mihenk", url, width=1280, height=800, min_size=(960, 640))
    webview.start()


def run_window_smoke(url: str, signal: SmokeSignal, timeout_s: float) -> bool:
    """Opens the real window; passes when the screens reach the server within timeout_s."""
    import webview

    window = webview.create_window("mihenk (release check)", url)
    if window is None:  # pywebview's stub allows None; it only happens when start() cancels it
        return False

    def watch() -> None:
        signal.event.wait(timeout_s)
        window.destroy()

    webview.start(watch)
    return signal.event.is_set()


def _wait_for_interrupt() -> None:
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        return


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mihenk", description="Track competitors' pricing and packaging."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--browser", action="store_true", help="open the screens in your web browser")
    mode.add_argument("--smoke", action="store_true", help="release check: open, connect, exit")
    parser.add_argument("--smoke-timeout", type=float, default=60.0, help=argparse.SUPPRESS)
    parser.add_argument("--data-dir", type=Path, default=None, help="use this data folder")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse(argv)
    data_dir: Path = args.data_dir or default_data_dir()
    logging.basicConfig(
        filename=logs_dir(data_dir) / "mihenk.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        encoding="utf-8",
    )
    sock = bind_loopback()
    port = int(sock.getsockname()[1])
    token = new_token()
    smoke = SmokeSignal() if args.smoke else None
    app = create_app(GuardConfig(port=port, token=token), bundled_web_dist(), smoke)
    server = ServerThread(app, sock)
    server.start()
    log.info("mihenk started on 127.0.0.1:%d", port)
    url = launch_url(port, token, smoke=args.smoke)
    try:
        if smoke is not None:
            return 0 if run_window_smoke(url, smoke, args.smoke_timeout) else 1
        if args.browser:
            webbrowser.open(url)
            _wait_for_interrupt()
            return 0
        run_window(url)
        return 0
    finally:
        server.stop()
