import logging
import socket
import sys
import threading
import types
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Self
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from mihenk.api.routes.smoke import SmokeSignal
from mihenk.api.security import TOKEN_HEADER, GuardConfig
from mihenk.api.server import create_app
from mihenk.app import launcher
from mihenk.app.launcher import bind_loopback, launch_url, new_token
from mihenk.app.paths import logs_dir


def test_bind_loopback_gives_a_free_local_port() -> None:
    sock = bind_loopback()
    try:
        host, port = sock.getsockname()[:2]
        assert host == "127.0.0.1"
        assert port > 0
        assert sock.family == socket.AF_INET
    finally:
        sock.close()


def test_tokens_are_long_unique_and_url_safe() -> None:
    tokens = {new_token() for _ in range(20)}
    assert len(tokens) == 20
    assert all(len(t) >= 40 and t.isascii() for t in tokens)
    assert all(
        set(t) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
        for t in tokens
    )


def test_launch_url_keeps_the_token_in_the_fragment() -> None:
    assert launch_url(5000, "abc") == "http://127.0.0.1:5000/#token=abc"
    assert launch_url(5000, "abc", smoke=True) == "http://127.0.0.1:5000/#token=abc&smoke=1"


def test_launch_url_fragment_round_trips_like_the_screens_parse_it() -> None:
    # web/src/api/client.ts reads location.hash with URLSearchParams; parse_qs is the same
    # grammar. Any token new_token() makes must come back byte for byte.
    for _ in range(50):
        token = new_token()
        fragment = urlsplit(launch_url(5000, token)).fragment
        assert parse_qs(fragment, strict_parsing=True) == {"token": [token]}
        smoke_fragment = urlsplit(launch_url(5000, token, smoke=True)).fragment
        assert parse_qs(smoke_fragment, strict_parsing=True) == {"token": [token], "smoke": ["1"]}


def test_data_dir_override_with_spaces_and_turkish_letters(tmp_path: Path) -> None:
    data_dir = tmp_path / "Ayşe Yılmaz" / "mihenk data"
    logs = logs_dir(data_dir)
    assert logs.is_dir()
    (logs / "probe.txt").write_text("şğıİ", encoding="utf-8")
    assert (logs / "probe.txt").read_text(encoding="utf-8") == "şğıİ"


# --- no other local program may share the port --------------------------------------------------


class _RecordingSocket:
    """Stands in for socket.socket and records the order of setsockopt and bind."""

    calls: list[tuple[object, ...]] = []  # noqa: RUF012 - reset by each test that uses it

    def __init__(self, *args: object) -> None:
        _RecordingSocket.calls.append(("socket", *args))

    def setsockopt(self, level: int, option: int, value: int) -> None:
        _RecordingSocket.calls.append(("setsockopt", level, option, value))

    def bind(self, address: object) -> None:
        _RecordingSocket.calls.append(("bind", address))


def test_bind_loopback_takes_the_port_exclusively_before_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # SO_EXCLUSIVEADDRUSE exists only on Windows; a made-up value lets this run everywhere.
    monkeypatch.setattr(socket, "SO_EXCLUSIVEADDRUSE", -5, raising=False)
    _RecordingSocket.calls = []
    monkeypatch.setattr(socket, "socket", _RecordingSocket)
    launcher.bind_loopback()
    assert [call[0] for call in _RecordingSocket.calls] == ["socket", "setsockopt", "bind"]
    assert _RecordingSocket.calls[1] == ("setsockopt", socket.SOL_SOCKET, -5, 1)
    assert _RecordingSocket.calls[2] == ("bind", ("127.0.0.1", 0))


def test_bind_loopback_still_works_where_the_option_does_not_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(socket, "SO_EXCLUSIVEADDRUSE", raising=False)
    _RecordingSocket.calls = []
    monkeypatch.setattr(socket, "socket", _RecordingSocket)
    launcher.bind_loopback()
    assert [call[0] for call in _RecordingSocket.calls] == ["socket", "bind"]


@pytest.mark.skipif(
    not hasattr(socket, "SO_EXCLUSIVEADDRUSE"), reason="SO_EXCLUSIVEADDRUSE is Windows only"
)
def test_bind_loopback_sets_the_exclusive_option_on_a_real_socket() -> None:
    sock = launcher.bind_loopback()
    try:
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE) != 0
    finally:
        sock.close()


@pytest.mark.skipif(
    not hasattr(socket, "SO_EXCLUSIVEADDRUSE"), reason="SO_EXCLUSIVEADDRUSE is Windows only"
)
def test_no_other_socket_can_share_the_port_even_with_reuseaddr() -> None:
    # A regression guard, not proof of the option: Windows 11 already refuses this for a socket
    # that did not set SO_REUSEADDR itself (checked on build 26300), with or without
    # SO_EXCLUSIVEADDRUSE. The test above is what proves the option is set.
    sock = launcher.bind_loopback()
    other = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        other.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        with pytest.raises(OSError):
            other.bind(("127.0.0.1", sock.getsockname()[1]))
    finally:
        other.close()
        sock.close()


# --- the token never reaches mihenk.log ---------------------------------------------------------

TOKEN = "AbC-dEf_123456789AbC-dEf_123456789AbC-dEf_1234"
URL = f"http://127.0.0.1:5000/#token={TOKEN}&smoke=1"


def _record(msg: object, args: Any = None) -> logging.LogRecord:
    return logging.LogRecord("pywebview", logging.DEBUG, __file__, 1, msg, args, None)


def test_filter_redacts_a_token_in_the_message() -> None:
    record = _record(f"Loading {URL}")
    assert launcher.TokenRedactingFilter().filter(record) is True
    assert record.getMessage() == "Loading http://127.0.0.1:5000/#token=<redacted>&smoke=1"


def test_filter_redacts_a_token_in_the_args() -> None:
    record = _record("Loading %s (attempt %d)", (URL, 2))
    assert launcher.TokenRedactingFilter().filter(record) is True
    assert (
        record.getMessage() == "Loading http://127.0.0.1:5000/#token=<redacted>&smoke=1 (attempt 2)"
    )
    assert TOKEN not in str(record.args)
    assert TOKEN not in str(record.msg)


def test_filter_redacts_a_token_in_a_mapping_arg() -> None:
    record = _record("Loading %(url)s", ({"url": URL},))
    assert launcher.TokenRedactingFilter().filter(record) is True
    assert TOKEN not in record.getMessage()
    assert "token=<redacted>" in record.getMessage()


def test_filter_redacts_a_token_in_an_exception_used_as_the_message() -> None:
    # pywebview calls logger.exception(e), so the message can be an exception object.
    record = _record(RuntimeError(f"cannot open {URL}"))
    assert launcher.TokenRedactingFilter().filter(record) is True
    assert TOKEN not in record.getMessage()
    assert "token=<redacted>" in record.getMessage()


@pytest.mark.parametrize(
    "text", ["Loading http://127.0.0.1:5000/", "token is a word here", "tokens=3 and mytoken"]
)
def test_filter_leaves_other_messages_alone(text: str) -> None:
    record = _record(text)
    assert launcher.TokenRedactingFilter().filter(record) is True
    assert record.getMessage() == text


def test_filter_leaves_formatting_alone_when_there_is_no_token() -> None:
    record = _record("%d windows, 100%% sure", (3,))
    assert launcher.TokenRedactingFilter().filter(record) is True
    assert record.msg == "%d windows, 100%% sure"
    assert record.getMessage() == "3 windows, 100% sure"


def test_filter_drops_a_record_it_cannot_format() -> None:
    # A format string that does not match its args would fail inside the handler; dropping the
    # record is safer than letting an unchecked message through.
    assert launcher.TokenRedactingFilter().filter(_record("%d", ("not a number",))) is False


@pytest.fixture
def pywebview_logger() -> Iterator[logging.Logger]:
    logger = logging.getLogger("pywebview")
    before = list(logger.filters)
    yield logger
    logger.filters[:] = before


def test_the_pywebview_logger_is_protected_once(pywebview_logger: logging.Logger) -> None:
    launcher.redact_tokens_in_pywebview_log()
    launcher.redact_tokens_in_pywebview_log()
    ours = [f for f in pywebview_logger.filters if isinstance(f, launcher.TokenRedactingFilter)]
    assert len(ours) == 1


def test_a_pywebview_log_line_reaches_the_log_without_the_token(
    pywebview_logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    launcher.redact_tokens_in_pywebview_log()
    with caplog.at_level(logging.DEBUG, logger="pywebview"):
        pywebview_logger.debug("Loading %s", URL)
        pywebview_logger.warning(f"Loading {URL}")
    assert caplog.text.count("token=<redacted>") == 2
    assert TOKEN not in caplog.text


# --- smoke mode stops waiting when the window is gone -------------------------------------------


def _finishes_within(seconds: float, target: Callable[[], object]) -> bool:
    """Runs target in a thread; True if it returned in time. An error in target is re-raised."""
    errors: list[BaseException] = []

    def run() -> None:
        try:
            target()
        except BaseException as exc:  # handed back to the test below
            errors.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(seconds)
    if errors:
        raise errors[0]
    return not thread.is_alive()


def test_wait_returns_at_once_when_the_window_is_already_closed() -> None:
    signal, closed = SmokeSignal(), threading.Event()
    closed.set()
    assert _finishes_within(2, lambda: launcher.wait_for_connect_or_close(signal, closed, 60))


def test_wait_returns_when_the_window_closes_while_waiting() -> None:
    signal, closed = SmokeSignal(), threading.Event()
    threading.Timer(0.1, closed.set).start()
    assert _finishes_within(2, lambda: launcher.wait_for_connect_or_close(signal, closed, 60))


def test_wait_returns_when_the_screens_connect() -> None:
    signal, closed = SmokeSignal(), threading.Event()
    threading.Timer(0.1, signal.event.set).start()
    assert _finishes_within(2, lambda: launcher.wait_for_connect_or_close(signal, closed, 60))


def test_wait_gives_up_after_the_timeout() -> None:
    signal, closed = SmokeSignal(), threading.Event()
    assert _finishes_within(2, lambda: launcher.wait_for_connect_or_close(signal, closed, 0.2))


class _FakeEvent:
    def __init__(self) -> None:
        self.handlers: list[Callable[[], object]] = []

    def __iadd__(self, handler: Callable[[], object]) -> Self:
        self.handlers.append(handler)
        return self

    def fire(self) -> None:
        for handler in self.handlers:
            handler()


class _FakeWindow:
    def __init__(self) -> None:
        self.events = types.SimpleNamespace(closed=_FakeEvent())
        self.destroyed = 0

    def destroy(self) -> None:
        self.destroyed += 1


def _fake_webview(
    monkeypatch: pytest.MonkeyPatch, while_open: Callable[[_FakeWindow], None]
) -> _FakeWindow:
    """A webview module whose start() runs while_open, then the watcher, in the calling thread."""
    window = _FakeWindow()

    def start(func: Callable[[], None]) -> None:
        while_open(window)
        func()

    module = types.SimpleNamespace(create_window=lambda *args, **kwargs: window, start=start)
    monkeypatch.setitem(sys.modules, "webview", module)
    return window


def test_smoke_does_not_linger_when_the_window_closes_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signal = SmokeSignal()
    window = _fake_webview(monkeypatch, lambda w: w.events.closed.fire())
    result: list[bool] = []
    done = _finishes_within(
        2, lambda: result.append(launcher.run_window_smoke("http://127.0.0.1:1/", signal, 60))
    )
    assert done, "run_window_smoke kept waiting after the window closed"
    assert result == [False]
    assert window.destroyed == 0  # nothing left to destroy


def test_smoke_passes_and_closes_the_window_once_the_screens_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signal = SmokeSignal()
    window = _fake_webview(monkeypatch, lambda _w: signal.event.set())
    assert launcher.run_window_smoke("http://127.0.0.1:1/", signal, 60) is True
    assert window.destroyed == 1


def test_smoke_fails_and_closes_the_window_after_the_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = _fake_webview(monkeypatch, lambda _w: None)
    assert launcher.run_window_smoke("http://127.0.0.1:1/", SmokeSignal(), 0.2) is False
    assert window.destroyed == 1


# --- main ---------------------------------------------------------------------------------------


class _Servers:
    """Collects every ServerThread main creates, and every stop() call."""

    def __init__(self) -> None:
        self.created: list[launcher.ServerThread] = []
        self.stopped: list[launcher.ServerThread] = []


@pytest.fixture
def servers(monkeypatch: pytest.MonkeyPatch) -> _Servers:
    seen = _Servers()
    real = launcher.ServerThread

    class Recording(real):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            seen.created.append(self)

        def stop(self, timeout_s: float = 10.0) -> None:
            seen.stopped.append(self)
            super().stop(timeout_s)

    monkeypatch.setattr(launcher, "ServerThread", Recording)
    return seen


def _token_and_port(url: str) -> tuple[str, int]:
    parts = urlsplit(url)
    assert parts.port is not None
    return parse_qs(parts.fragment)["token"][0], parts.port


def test_main_smoke_exits_0_when_the_screens_connect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, servers: _Servers
) -> None:
    seen: dict[str, Any] = {}

    def fake_smoke(url: str, signal: SmokeSignal, timeout_s: float) -> bool:
        token, port = _token_and_port(url)
        base = f"http://127.0.0.1:{port}"
        seen["url"], seen["timeout"] = url, timeout_s
        seen["running"] = servers.created[0].running
        # What the real screens do: call the server with the launch token.
        reply = httpx.post(f"{base}/api/smoke/ok", headers={TOKEN_HEADER: token, "origin": base})
        seen["status"] = reply.status_code
        return signal.event.is_set()

    monkeypatch.setattr(launcher, "run_window_smoke", fake_smoke)
    code = launcher.main(["--smoke", "--smoke-timeout", "7", "--data-dir", str(tmp_path / "data")])
    assert code == 0
    assert seen["status"] == 200
    assert seen["running"] is True  # the server was up before the window opened
    assert seen["timeout"] == 7
    assert parse_qs(urlsplit(seen["url"]).fragment)["smoke"] == ["1"]
    assert servers.stopped == servers.created
    assert not servers.created[0].running


def test_main_smoke_exits_1_when_the_screens_never_connect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, servers: _Servers
) -> None:
    monkeypatch.setattr(launcher, "run_window_smoke", lambda url, signal, timeout_s: False)
    assert launcher.main(["--smoke", "--data-dir", str(tmp_path / "data")]) == 1
    assert servers.stopped == servers.created
    assert not servers.created[0].running


def test_main_opens_the_window_without_smoke_and_stops_the_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, servers: _Servers
) -> None:
    urls: list[str] = []
    monkeypatch.setattr(launcher, "run_window", urls.append)
    assert launcher.main(["--data-dir", str(tmp_path / "data")]) == 0
    assert len(urls) == 1
    assert "smoke" not in parse_qs(urlsplit(urls[0]).fragment)
    assert servers.stopped == servers.created
    assert not servers.created[0].running


def test_main_in_browser_mode_opens_the_browser_and_stops_the_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, servers: _Servers
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: opened.append(url) or True)
    monkeypatch.setattr(launcher, "_wait_for_interrupt", lambda: None)
    assert launcher.main(["--browser", "--data-dir", str(tmp_path / "data")]) == 0
    assert len(opened) == 1
    assert urlsplit(opened[0]).hostname == "127.0.0.1"
    assert servers.stopped == servers.created


def test_main_creates_the_logs_folder_in_a_data_dir_with_spaces_and_turkish_letters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, servers: _Servers
) -> None:
    data_dir = tmp_path / "veri klasörü ışık"
    monkeypatch.setattr(launcher, "run_window", lambda url: None)
    assert launcher.main(["--data-dir", str(data_dir)]) == 0
    assert (data_dir / "logs").is_dir()


def test_main_protects_the_pywebview_log_from_the_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    servers: _Servers,
    pywebview_logger: logging.Logger,
) -> None:
    monkeypatch.setattr(launcher, "run_window", lambda url: None)
    launcher.main(["--data-dir", str(tmp_path / "data")])
    assert any(isinstance(f, launcher.TokenRedactingFilter) for f in pywebview_logger.filters)


def test_main_logs_a_server_that_does_not_start_and_returns_1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    servers: _Servers,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def refuse(self: launcher.ServerThread, timeout_s: float = 10.0) -> None:
        raise launcher.ServerStartError("the local server did not start in time")

    monkeypatch.setattr(launcher.ServerThread, "start", refuse)
    opened: list[str] = []
    monkeypatch.setattr(launcher, "run_window", opened.append)
    assert launcher.main(["--data-dir", str(tmp_path / "data")]) == 1
    assert opened == []  # no window for a server that is not there
    assert servers.stopped == servers.created  # and the socket is still released
    failures = [r for r in caplog.records if r.levelno == logging.ERROR and r.exc_info]
    assert len(failures) == 1
    assert "did not start in time" in caplog.text


def test_main_logs_any_other_failure_and_returns_1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    servers: _Servers,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken(url: str) -> None:
        raise RuntimeError("window library missing")

    monkeypatch.setattr(launcher, "run_window", broken)
    assert launcher.main(["--data-dir", str(tmp_path / "data")]) == 1
    assert servers.stopped == servers.created
    assert any(r.levelno == logging.ERROR and r.exc_info for r in caplog.records)
    assert "window library missing" in caplog.text


def test_stopping_a_server_thread_that_never_started_is_safe() -> None:
    sock = launcher.bind_loopback()
    config = GuardConfig(port=sock.getsockname()[1], token=launcher.new_token())
    server = launcher.ServerThread(create_app(config, None), sock)
    server.stop()
    assert not server.running


# --- --browser says where the one-time key ends up ----------------------------------------------


def test_browser_option_help_mentions_the_browser_history(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        launcher.main(["--help"])
    help_text = " ".join(capsys.readouterr().out.split())
    assert "--browser" in help_text
    assert "history" in help_text
    assert "one-time key" in help_text


# --- the command line: capture and install-browser go to cli.main --------------------------------


@pytest.mark.parametrize("command", ["capture", "install-browser"])
def test_command_line_commands_are_handed_to_the_cli(
    command: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr(launcher.cli, "main", lambda argv: seen.append(list(argv)) or 7)
    monkeypatch.setattr(launcher, "_run", lambda args: pytest.fail("the window must not open"))
    assert launcher.main([command, "http://127.0.0.1/x", "--key", "k"]) == 7
    assert seen == [[command, "http://127.0.0.1/x", "--key", "k"]]


def test_without_an_argument_the_command_line_is_sys_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    # The console script and `python -m mihenk` call main() with no argument.
    seen: list[list[str]] = []
    monkeypatch.setattr(launcher.cli, "main", lambda argv: seen.append(list(argv)) or 3)
    monkeypatch.setattr(sys, "argv", ["mihenk", "capture", "http://127.0.0.1/x"])
    assert launcher.main() == 3
    assert seen == [["capture", "http://127.0.0.1/x"]]


def test_window_options_are_not_handed_to_the_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, servers: _Servers
) -> None:
    monkeypatch.setattr(launcher.cli, "main", lambda argv: pytest.fail("not a cli command"))
    monkeypatch.setattr(launcher, "run_window", lambda url: None)
    assert launcher.main(["--data-dir", str(tmp_path / "data")]) == 0
