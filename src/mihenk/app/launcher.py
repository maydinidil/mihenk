"""Starts mihenk: data folder, local server, window (design §5).

The window owns the main thread, as pywebview requires. The server runs under uvicorn in a
background thread and is told to exit when the window closes.
"""

from __future__ import annotations

import argparse
import logging
import re
import secrets
import socket
import sys
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
    # Windows only: no other program may bind this port while we hold it, whatever options it
    # sets, so none can be handed connections that carry the token. This is Microsoft's guard
    # against port hijacking; Windows 11 already refuses the common case, and this makes it
    # explicit. It must come before bind(). getattr keeps the file type-checkable on macOS, where
    # the constant does not exist.
    exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    if exclusive is not None:
        sock.setsockopt(socket.SOL_SOCKET, exclusive, 1)
    sock.bind(("127.0.0.1", 0))
    return sock


def launch_url(port: int, token: str, *, smoke: bool = False) -> str:
    fragment = f"token={token}" + ("&smoke=1" if smoke else "")
    return f"http://127.0.0.1:{port}/#{fragment}"


def bundled_web_dist() -> Path:
    return Path(str(resources.files("mihenk") / "web_dist"))


_TOKEN_IN_TEXT = re.compile(r"token=[^&\s'\"#]+")


class TokenRedactingFilter(logging.Filter):
    """Replaces token=<value> with token=<redacted> in a log record's message and traceback.

    pywebview logs the address it loads (Window.load_url, at PYWEBVIEW_LOG=DEBUG), and that
    address carries the one-time key; an exception that mentions the address carries it into the
    traceback too. The key is in msg or in args depending on how the line was logged, so this
    looks at the formatted message. A record that cannot be formatted is dropped: the handler
    would fail on it anyway, and an unchecked message must not reach the file.

    It belongs on the log file's handler (see `open_log_file`), which every logger's records
    reach. The traceback text is made here, from `exc_info`, when the formatter has not yet
    made it: the formatter would make it after this filter has run, out of reach.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return False
        redacted = _TOKEN_IN_TEXT.sub("token=<redacted>", message)
        if redacted != message:
            record.msg = redacted
            record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = _TOKEN_IN_TEXT.sub("token=<redacted>", record.exc_text)
        return True


def open_log_file(path: Path) -> logging.Handler:
    """The handler for mihenk.log: every record written to the file passes the token filter."""
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(TokenRedactingFilter())
    return handler


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
        # join() raises on a thread that never started, which is what a failed start() leaves.
        if self._thread.is_alive():
            self._thread.join(timeout_s)
        self._sock.close()

    @property
    def running(self) -> bool:
        return self._thread.is_alive()


def run_window(url: str) -> None:
    import webview

    webview.create_window("mihenk", url, width=1280, height=800, min_size=(960, 640))
    webview.start()


_POLL_S = 0.05


def wait_for_connect_or_close(
    signal: SmokeSignal, window_closed: threading.Event, timeout_s: float
) -> None:
    """Returns when the screens connect, the window closes, or timeout_s has passed."""
    deadline = time.monotonic() + timeout_s
    while not (signal.event.is_set() or window_closed.is_set()):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        # Two events cannot be waited on at once: sleep on the one that ends the wait at once
        # and look at the other every few milliseconds.
        window_closed.wait(min(_POLL_S, remaining))


def run_window_smoke(url: str, signal: SmokeSignal, timeout_s: float) -> bool:
    """Opens the real window; passes when the screens reach the server within timeout_s."""
    import webview

    window = webview.create_window("mihenk (release check)", url)
    if window is None:  # pywebview's stub allows None; it only happens when start() cancels it
        return False
    window_closed = threading.Event()
    window.events.closed += window_closed.set

    def watch() -> None:
        # The watcher is a non-daemon thread, so if it kept waiting after the window was closed
        # the process would stay alive until the timeout ran out.
        wait_for_connect_or_close(signal, window_closed, timeout_s)
        if not window_closed.is_set():
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
    mode.add_argument(
        "--browser",
        action="store_true",
        help="open the screens in your web browser; the address, with its one-time key, "
        "stays in the browser's history",
    )
    mode.add_argument("--smoke", action="store_true", help="release check: open, connect, exit")
    parser.add_argument("--smoke-timeout", type=float, default=60.0, help=argparse.SUPPRESS)
    parser.add_argument("--data-dir", type=Path, default=None, help="use this data folder")
    return parser.parse_args(argv)


# The first argument that hands the whole command line to the command-line interface instead of
# opening the window. `_playwright-install` is how a frozen app (no `-m mihenk`) reaches
# Playwright's own command line for the Chromium download.
_CLI_COMMANDS = frozenset({"capture", "install-browser", "_playwright-install"})


def main(argv: Sequence[str] | None = None) -> int:
    # The console script and `python -m mihenk` call this with no argument: the command line is
    # then sys.argv[1:].
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] in _CLI_COMMANDS:
        # Imported here and not at the top: the command line loads Playwright and httpx2
        # (about 0.28 s), which opening the window does not need.
        from mihenk import cli

        return cli.main(arguments)
    args = _parse(argv)  # --help and a bad option exit here, as argparse does
    try:
        return _run(args)
    except Exception:
        # The windowed build has no console, so mihenk.log is the only place a failure shows.
        log.exception("mihenk stopped because of an unexpected error")
        return 1


def _run(args: argparse.Namespace) -> int:
    data_dir: Path = args.data_dir or default_data_dir()
    logging.basicConfig(
        level=logging.INFO, handlers=[open_log_file(logs_dir(data_dir) / "mihenk.log")]
    )
    sock = bind_loopback()
    port = int(sock.getsockname()[1])
    token = new_token()
    smoke = SmokeSignal() if args.smoke else None
    app = create_app(GuardConfig(port=port, token=token), bundled_web_dist(), smoke)
    server = ServerThread(app, sock)
    url = launch_url(port, token, smoke=args.smoke)
    try:
        server.start()
        log.info("mihenk started on 127.0.0.1:%d", port)
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
