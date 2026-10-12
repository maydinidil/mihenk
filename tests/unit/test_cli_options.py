"""The command line's pure parts and its refusals. Nothing here reaches a web page."""

from __future__ import annotations

import io
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from mihenk import cli
from mihenk.capture import browser as browser_module
from mihenk.capture.models import SAFE_SEGMENT
from mihenk.capture.snapshot import new_run_id, snapshot_path_too_long

# --- the region of a locale name ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "region"),
    [
        ("en_NL", "NL"),
        ("en-NL", "NL"),
        ("nl-nl", "NL"),
        ("tr_TR.UTF-8", "TR"),
        ("en_US@euro", "US"),
        ("zh-Hans-CN", "CN"),  # Windows names can carry a script
        ("sr-Latn-RS", "RS"),
        # Windows' locale.getlocale() gives a long English name: the country spelled out is not
        # a region, and must not turn into "NETHERLANDS".
        ("English_Netherlands", "ZZ"),
        ("English_United States.1252", "ZZ"),
        ("Turkish_Türkiye.1254", "ZZ"),
        ("C", "ZZ"),
        ("POSIX", "ZZ"),
        ("en", "ZZ"),
        ("es-419", "ZZ"),
        ("zh-Hant", "ZZ"),
        ("en-N1", "ZZ"),
        ("en-ŞŞ", "ZZ"),
        ("", "ZZ"),
        (None, "ZZ"),
    ],
)
def test_region_from_locale(name: str | None, region: str) -> None:
    assert cli.region_from_locale(name) == region


def test_the_system_locale_gives_a_two_letter_region_or_unknown() -> None:
    name = cli.system_locale_name()
    assert name is None or isinstance(name, str)
    assert re.fullmatch("[A-Z]{2}", cli.region_from_locale(name))


# --- the default page key -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "key"),
    [
        ("http://127.0.0.1:5000/static-table", "127-0-0-1-static-table"),
        ("https://www.Example.com/en/Pricing/?plan=1#top", "www-example-com-en-pricing"),
        ("https://example.com", "example-com"),
        ("https://example.com:8443/", "example-com"),  # no port in the key
        ("https://bücher.example/preise", "xn-bcher-kva-example-preise"),
        ("http://nul/", "page-nul"),  # a name Windows reserves for a device
        ("http://[::1/x", "page"),  # not a URL; the capture refuses it later
        ("", "page"),
    ],
)
def test_default_key(url: str, key: str) -> None:
    assert cli.default_key(url) == key
    assert SAFE_SEGMENT.fullmatch(key)


def test_default_key_is_at_most_64_characters_and_never_ends_in_a_dash() -> None:
    key = cli.default_key("https://example.com/" + "pricing/" * 30)
    assert len(key) <= 64
    assert not key.endswith("-")
    assert SAFE_SEGMENT.fullmatch(key)
    # 63 characters of host, a dash, then the path: the cut falls on the dash.
    edge = cli.default_key("https://" + "a" * 63 + ".example/x")
    assert len(edge) <= 64
    assert not edge.endswith("-")
    assert SAFE_SEGMENT.fullmatch(edge)


# --- command lines the command refuses (exit 2, before anything is requested) -------------------


def _refused(
    argv: list[str], capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> tuple[int, str]:
    code = cli.main([*argv, "--data-dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert captured.out == ""
    assert list(tmp_path.iterdir()) == []
    return code, captured.err


def test_no_command_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 2
    assert "usage" in capsys.readouterr().err


def test_help_exits_zero_and_describes_the_options(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["capture", "--help"]) == 0
    text = " ".join(capsys.readouterr().out.split())
    for option in ("--key", "--method", "--state", "--ignore-robots", "--country", "--data-dir"):
        assert option in text


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["capture", "http://127.0.0.1/x", "--key", "Not Safe"], "a key is 1 to 64"),
        (["capture", "http://127.0.0.1/x", "--key", "nul"], "a key is 1 to 64"),
        (["capture", "http://127.0.0.1/x", "--country", "NLD"], "a country is two letters"),
        (["capture", "http://127.0.0.1/x", "--country", "N1"], "a country is two letters"),
        (["capture", "http://127.0.0.1/x", "--method", "scrape"], "invalid choice"),
        (["capture"], "the following arguments are required"),
    ],
)
def test_bad_options_are_refused_with_exit_2(
    argv: list[str], message: str, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code, err = _refused(argv, capsys, tmp_path)
    assert code == 2
    assert message in err


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        # State labels are folder names.
        (["--state", "Monthly=Monthly"], "unsafe state label"),
        (["--state", "a b"], "unsafe state label"),
        (["--state", "monthly="], "at least 1 character"),
        # A fetch or render recipe is one state with no actions.
        (["--method", "fetch", "--state", "monthly=Monthly"], "exactly one state and no actions"),
        (["--method", "render", "--state", "a", "--state", "b"], "exactly one state"),
        (["--method", "render_interact", "--state", "a", "--state", "a=Go"], "must be unique"),
    ],
)
def test_bad_states_are_refused_with_exit_2(
    argv: list[str], message: str, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code, err = _refused(["capture", "http://127.0.0.1/x", *argv], capsys, tmp_path)
    assert code == 2
    assert message in err
    assert err.startswith("mihenk capture: error: ")
    assert len(err.strip().splitlines()) == 1


class _Started(Exception):
    """Raised by a stand-in for something that must not start."""


def _nothing_may_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """Playwright and the http client: either one starting fails the test."""

    def playwright_started() -> object:
        raise _Started("Playwright was started")

    def client_opened(locale: str) -> object:
        raise _Started("an http client was opened")

    monkeypatch.setattr(cli, "sync_playwright", playwright_started)
    monkeypatch.setattr(cli, "make_client", client_opened)


@pytest.mark.parametrize("method", ["fetch", "render", "render_interact"])
@pytest.mark.parametrize(
    "url",
    [
        "gopher://127.0.0.1/",
        "ftp://127.0.0.1/pricing",
        "file:///C:/pricing.html",
        "javascript:alert(1)",
        "http://",
        "https:///pricing",
        "http://127.0.0.1:0/",
        "http://127.0.0.1:99999/",
        "http://127.0.0.1:abc/",
        "http://[::1/pricing",
        "pricing",
        " ",
    ],
)
def test_a_url_that_is_not_http_with_a_host_exits_2_before_anything_starts(
    url: str,
    method: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _nothing_may_start(monkeypatch)
    code, err = _refused(["capture", url, "--method", method], capsys, tmp_path)
    assert code == 2
    assert err.startswith("mihenk capture: error: not a valid http(s) URL: ")
    assert len(err.strip().splitlines()) == 1


def test_a_very_long_bad_url_is_cut_in_the_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _nothing_may_start(monkeypatch)
    code, err = _refused(["capture", "gopher://" + "a" * 5000], capsys, tmp_path)
    assert code == 2
    assert len(err) < 400


def _deep_data_dir(tmp_path: Path, label: str) -> Path:
    """A data folder whose snapshot path fits the limit with a short state label and not with
    `label`, found by asking the rule itself (the run id has a fixed length)."""
    run_id = new_run_id(datetime.now(UTC))
    key = "127-0-0-1-x"
    for pad in range(1, 400):
        data_dir = tmp_path / ("d" * pad)
        root = data_dir / "snapshots"
        if snapshot_path_too_long(root, run_id, key, label):
            assert not snapshot_path_too_long(root, run_id, key, "a")
            return data_dir
    raise AssertionError("no data folder length found")


def test_the_longest_state_label_decides_whether_the_snapshot_path_fits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _nothing_may_start(monkeypatch)
    long_label = "s" * 64
    data_dir = _deep_data_dir(tmp_path, long_label)
    code = cli.main(
        [
            "capture",
            "http://127.0.0.1/x",
            "--key",
            "127-0-0-1-x",
            "--method",
            "render_interact",
            "--state",
            "a",
            "--state",
            long_label,
            "--data-dir",
            str(data_dir),
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert captured.err.startswith("mihenk capture: error: the data folder is too deep")
    assert len(captured.err.strip().splitlines()) == 1
    assert not data_dir.exists()
    # With only the short label the same data folder is accepted: the capture goes on and
    # reaches the (stood-in) client, which is the point where nothing may start.
    with pytest.raises(_Started):
        cli.main(
            [
                "capture",
                "http://127.0.0.1/x",
                "--key",
                "127-0-0-1-x",
                "--method",
                "render_interact",
                "--state",
                "a",
                "--state",
                "b",
                "--data-dir",
                str(data_dir),
            ]
        )


def _set_proxy_variables(monkeypatch: pytest.MonkeyPatch, proxy: str) -> None:
    """The user's proxy setting, as the app reads it. The suite's autouse fixture sets
    `NO_PROXY=*` so that tests go direct; a test of the app's proxy handling takes that back."""
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, proxy)


def test_a_malformed_proxy_variable_is_one_line_and_exit_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _set_proxy_variables(monkeypatch, "ftp://127.0.0.1:9")
    code, err = _refused(["capture", "http://127.0.0.1/x"], capsys, tmp_path)
    assert code == 2
    assert err.startswith("mihenk capture: error: cannot set up the http client: ")
    assert len(err.strip().splitlines()) == 1


def test_a_proxy_that_needs_a_missing_package_is_one_line_and_exit_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _set_proxy_variables(monkeypatch, "socks5://127.0.0.1:9")
    code, err = _refused(["capture", "http://127.0.0.1/x"], capsys, tmp_path)
    assert code == 2
    assert "cannot set up the http client" in err
    assert len(err.strip().splitlines()) == 1


# --- output -------------------------------------------------------------------------------------


def test_a_console_that_cannot_show_a_letter_gets_a_question_mark() -> None:
    raw = io.BytesIO()
    console = io.TextIOWrapper(
        raw, encoding="ascii", errors="strict", newline="\n", write_through=True
    )
    cli._emit(console, "Aylık 199 TL")
    assert raw.getvalue() == b"Ayl?k 199 TL\n"


def test_no_console_at_all_is_not_an_error() -> None:
    cli._emit(None, "anything")


def test_the_pace_between_requests_to_one_site_is_two_seconds() -> None:
    assert cli.PACE_INTERVAL_S == 2.0


# --- Ctrl+C -------------------------------------------------------------------------------------


class _Recorder:
    """What was closed or left, in order."""

    def __init__(self) -> None:
        self.events: list[str] = []


def _interrupt(*args: Any, **kwargs: Any) -> Any:
    raise KeyboardInterrupt


def _watch_the_client(monkeypatch: pytest.MonkeyPatch, recorder: _Recorder) -> None:
    class Client:
        def close(self) -> None:
            recorder.events.append("client closed")

    monkeypatch.setattr(cli, "make_client", lambda locale: Client())


def _assert_stopped(code: int, capsys: pytest.CaptureFixture[str]) -> None:
    captured = capsys.readouterr()
    assert code == 130
    assert captured.out == ""
    assert captured.err == "Stopped.\n"  # no traceback


def test_ctrl_c_during_a_fetch_capture_is_130_and_the_client_is_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    recorder = _Recorder()
    _watch_the_client(monkeypatch, recorder)
    monkeypatch.setattr(cli, "capture_page", _interrupt)
    code = cli.main(["capture", "http://127.0.0.1/x", "--data-dir", str(tmp_path)])
    _assert_stopped(code, capsys)
    assert recorder.events == ["client closed", "client closed"]  # the page's and robots.txt's


class _Session:
    """Stands in for `sync_playwright()`: records when it is entered and when it is stopped."""

    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder

    def __enter__(self) -> object:
        self._recorder.events.append("playwright started")
        return object()

    def __exit__(self, *exc: object) -> None:
        self._recorder.events.append("playwright stopped")


def _fake_browser_run(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder, capture: Any, launch: Any = None
) -> None:
    class Browser:
        def close(self) -> None:
            recorder.events.append("browser closed")

    def launched(pw: object, **kwargs: Any) -> browser_module.LaunchedBrowser:
        return browser_module.LaunchedBrowser("chrome", Browser())  # type: ignore[arg-type]

    monkeypatch.setattr(cli, "sync_playwright", lambda: _Session(recorder))
    monkeypatch.setattr(cli, "launch_browser", launch or launched)
    monkeypatch.setattr(cli, "capture_page", capture)


def _render_argv(tmp_path: Path) -> list[str]:
    return ["capture", "http://127.0.0.1/x", "--method", "render", "--data-dir", str(tmp_path)]


def test_without_ctrl_c_a_render_capture_closes_the_browser_then_playwright_then_the_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorder = _Recorder()
    _watch_the_client(monkeypatch, recorder)
    _fake_browser_run(monkeypatch, recorder, lambda spec, ctx: [])
    assert cli.main(_render_argv(tmp_path)) == 0
    assert recorder.events == [
        "playwright started",
        "browser closed",
        "playwright stopped",
        "client closed",
        "client closed",
    ]


def test_ctrl_c_during_a_render_capture_skips_playwrights_cleanup_but_closes_the_client(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    recorder = _Recorder()
    _watch_the_client(monkeypatch, recorder)
    _fake_browser_run(monkeypatch, recorder, _interrupt)
    code = cli.main(_render_argv(tmp_path))
    _assert_stopped(code, capsys)
    # Neither the browser nor the Playwright session was closed: their sync calls hang mid-interrupt.
    assert recorder.events == ["playwright started", "client closed", "client closed"]


def test_ctrl_c_while_the_browser_launches_skips_playwrights_cleanup_too(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    recorder = _Recorder()
    _watch_the_client(monkeypatch, recorder)
    _fake_browser_run(monkeypatch, recorder, lambda spec, ctx: [], launch=_interrupt)
    code = cli.main(_render_argv(tmp_path))
    _assert_stopped(code, capsys)
    assert recorder.events == ["playwright started", "client closed", "client closed"]


def test_ctrl_c_during_the_download_is_130(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "install_chromium", _interrupt)
    code = cli.main(["install-browser", "--yes", "--data-dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == 130
    assert captured.err == "Stopped.\n"
    assert "Done" not in captured.out


def test_ctrl_c_at_the_install_prompt_is_130(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr("builtins.input", _interrupt)
    monkeypatch.setattr(cli, "install_chromium", lambda data_dir: pytest.fail("asked, then ran"))
    code = cli.main(["install-browser", "--data-dir", str(tmp_path)])
    assert code == 130
    assert capsys.readouterr().err == "Stopped.\n"


def test_ctrl_c_during_the_hidden_playwright_entry_is_130(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "playwright_main", _interrupt)
    saved = list(sys.argv)
    code = cli.main(["_playwright-install", "install", "chromium"])
    assert code == 130
    assert capsys.readouterr().err == "Stopped.\n"
    assert sys.argv == saved  # the borrowed argv was put back
