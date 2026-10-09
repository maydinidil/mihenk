"""Playwright's own Chromium: where it goes, how it is installed, and the consent that comes first.

Nothing here downloads anything. `subprocess.run` and Playwright's own command-line entry are
replaced wherever a test reaches the code that would start the download.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Playwright

from mihenk import cli
from mihenk.capture import browser
from mihenk.capture.browser import (
    LOOPBACK_ONLY_VARIABLE,
    BrowserUnavailable,
    browsers_dir,
    has_downloaded_chromium,
    install_chromium,
    install_command,
    launch_browser,
    start_playwright_env,
)

# The empty file Playwright writes into a browser folder once it has extracted all of it.
COMPLETE_MARKER = "INSTALLATION_COMPLETE"


def _finished_download(data_dir: Path, name: str = "chromium-1243") -> Path:
    """A browser folder as a finished Playwright download leaves it."""
    folder = browsers_dir(data_dir) / name
    folder.mkdir(parents=True)
    (folder / COMPLETE_MARKER).write_text("", encoding="utf-8")
    return folder


# --- the install command ------------------------------------------------------------------------


def test_install_command_when_running_from_source(tmp_path: Path) -> None:
    command, env = install_command(tmp_path, frozen=False)
    assert command == [
        sys.executable,
        "-m",
        "mihenk",
        "_playwright-install",
        "install",
        "chromium",
        "--no-shell",
    ]
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == str(browsers_dir(tmp_path))


def test_install_command_when_frozen(tmp_path: Path) -> None:
    command, _ = install_command(tmp_path, frozen=True)
    assert command == [sys.executable, "_playwright-install", "install", "chromium", "--no-shell"]


def test_browsers_live_in_the_data_folder(tmp_path: Path) -> None:
    assert browsers_dir(tmp_path) == tmp_path / "browsers"


# --- finding a downloaded Chromium --------------------------------------------------------------


def test_detects_a_downloaded_chromium(tmp_path: Path) -> None:
    assert not has_downloaded_chromium(tmp_path)
    _finished_download(tmp_path)
    assert has_downloaded_chromium(tmp_path)


def test_a_folder_without_the_complete_marker_is_not_a_download(tmp_path: Path) -> None:
    folder = browsers_dir(tmp_path) / "chromium-1243"
    folder.mkdir(parents=True)
    assert not has_downloaded_chromium(tmp_path)  # empty
    (folder / "chrome-win64").mkdir()
    (folder / "chrome-win64" / "chrome.exe").write_bytes(b"half")
    assert not has_downloaded_chromium(tmp_path)  # extracted in part, never marked
    (folder / COMPLETE_MARKER).write_text("", encoding="utf-8")
    assert has_downloaded_chromium(tmp_path)  # Playwright's mark makes it count


def test_an_unfinished_revision_does_not_hide_a_finished_one(tmp_path: Path) -> None:
    (browsers_dir(tmp_path) / "chromium-1300").mkdir(parents=True)
    assert not has_downloaded_chromium(tmp_path)
    _finished_download(tmp_path, "chromium-1243")
    assert has_downloaded_chromium(tmp_path)


def test_a_marker_that_is_a_folder_does_not_count(tmp_path: Path) -> None:
    (browsers_dir(tmp_path) / "chromium-1243" / COMPLETE_MARKER).mkdir(parents=True)
    assert not has_downloaded_chromium(tmp_path)


def test_an_empty_browsers_folder_has_no_chromium(tmp_path: Path) -> None:
    browsers_dir(tmp_path).mkdir()
    assert not has_downloaded_chromium(tmp_path)


def test_the_headless_shell_and_other_browsers_are_not_a_chromium(tmp_path: Path) -> None:
    for name in ("chromium_headless_shell-1243", "ffmpeg-1011", "firefox-1500"):
        _finished_download(tmp_path, name)  # finished, but not a Chromium
    assert not has_downloaded_chromium(tmp_path)


def test_a_file_called_chromium_is_not_a_download(tmp_path: Path) -> None:
    browsers_dir(tmp_path).mkdir()
    (browsers_dir(tmp_path) / "chromium-1243").write_text("not a folder", encoding="utf-8")
    assert not has_downloaded_chromium(tmp_path)


# --- the order the browsers are tried in ---------------------------------------------------------


class _Chromium:
    """Stands in for `playwright.chromium`: records the channels tried, in order."""

    def __init__(self, working: set[str], not_found: str) -> None:
        self.working = working
        self.not_found = not_found
        self.tried: list[str] = []
        self.options: list[dict[str, Any]] = []  # what each launch got besides channel, headless

    def launch(self, *, channel: str, headless: bool, **options: Any) -> str:
        self.tried.append(channel)
        self.options.append(options)
        if channel not in self.working:
            raise PlaywrightError(self.not_found.format(channel=channel))
        return f"browser {channel}"


_NOT_FOUND = "Chromium distribution '{channel}' is not found at C:/somewhere/chrome.exe"


def _playwright(
    working: set[str] | None = None, not_found: str = _NOT_FOUND
) -> tuple[Playwright, _Chromium]:
    chromium = _Chromium(working or set(), not_found)
    return cast(Playwright, SimpleNamespace(chromium=chromium)), chromium


def test_a_downloaded_chromium_is_tried_last_after_chrome_and_edge() -> None:
    pw, chromium = _playwright()
    with pytest.raises(BrowserUnavailable) as raised:
        launch_browser(pw, allow_downloaded=True)
    assert chromium.tried == ["chrome", "msedge", "chromium"]
    assert raised.value.tried == ("chrome", "msedge", "chromium")


def test_the_downloaded_chromium_is_never_tried_without_consent() -> None:
    pw, chromium = _playwright(working={"chromium"})  # it would launch, if it were tried
    with pytest.raises(BrowserUnavailable) as raised:
        launch_browser(pw)
    assert chromium.tried == ["chrome", "msedge"]
    assert raised.value.tried == ("chrome", "msedge")
    with pytest.raises(BrowserUnavailable):
        launch_browser(pw, allow_downloaded=False)
    assert "chromium" not in chromium.tried


@pytest.mark.parametrize(
    ("working", "tried", "channel"),
    [
        ({"chrome", "msedge", "chromium"}, ["chrome"], "chrome"),
        ({"msedge", "chromium"}, ["chrome", "msedge"], "msedge"),
        ({"chromium"}, ["chrome", "msedge", "chromium"], "chromium"),
    ],
)
def test_the_first_browser_that_launches_ends_the_search(
    working: set[str], tried: list[str], channel: str
) -> None:
    pw, chromium = _playwright(working=working)
    launched = launch_browser(pw, allow_downloaded=True)
    assert chromium.tried == tried
    assert launched.channel == channel


def test_a_chromium_that_is_not_downloaded_is_a_missing_browser_not_an_error() -> None:
    # Playwright words a missing download differently from a missing Chrome or Edge.
    missing = "Executable doesn't exist at C:/browsers/{channel}/chrome.exe"
    pw, chromium = _playwright(not_found=missing)
    with pytest.raises(BrowserUnavailable):
        launch_browser(pw, allow_downloaded=True)
    assert chromium.tried == ["chrome", "msedge", "chromium"]


# --- a browser that reaches nothing but this machine ---------------------------------------------


def test_with_the_loopback_variable_every_launch_gets_the_host_rules_and_a_dead_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(LOOPBACK_ONLY_VARIABLE, "1")
    pw, chromium = _playwright()  # nothing launches, so every channel is tried
    with pytest.raises(BrowserUnavailable):
        launch_browser(pw, allow_downloaded=True)
    expected = {
        "args": ["--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"],
        "proxy": {"server": "http://127.0.0.1:9", "bypass": "127.0.0.1"},
    }
    assert chromium.options == [expected, expected, expected]


def test_the_loopback_options_reach_the_launch_that_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(LOOPBACK_ONLY_VARIABLE, "1")
    pw, chromium = _playwright(working={"chrome"})
    assert launch_browser(pw).channel == "chrome"
    (options,) = chromium.options
    assert options["args"] == ["--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"]
    assert options["proxy"] == {"server": "http://127.0.0.1:9", "bypass": "127.0.0.1"}


def test_without_the_loopback_variable_the_launch_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(LOOPBACK_ONLY_VARIABLE, raising=False)
    pw, chromium = _playwright(working={"chrome"})
    launch_browser(pw)
    assert chromium.options == [{}]  # neither args nor proxy


@pytest.mark.parametrize("value", ["", "0", "true", "yes", "on", " 1"])
def test_only_the_value_1_turns_the_loopback_limit_on(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(LOOPBACK_ONLY_VARIABLE, value)
    pw, chromium = _playwright(working={"chrome"})
    launch_browser(pw)
    assert chromium.options == [{}]


def test_the_suite_sets_the_variable_for_its_own_browsers_and_children() -> None:
    # tests/conftest.py sets it at session start (before the browser fixtures launch) and again
    # for each test; a child process this test starts inherits it.
    assert os.environ[LOOPBACK_ONLY_VARIABLE] == "1"
    result = subprocess.run(
        [sys.executable, "-c", f"import os; print(os.environ.get({LOOPBACK_ONLY_VARIABLE!r}))"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.stdout.strip() == "1"


# --- the environment Playwright starts with -----------------------------------------------------


def test_start_playwright_env_points_playwright_at_the_data_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Setting a value first makes monkeypatch restore the variable afterwards, whether or not it
    # existed: the setting is process-wide and the test session shares one Playwright.
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "somewhere-else")
    start_playwright_env(tmp_path)
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(browsers_dir(tmp_path))


# --- running the install ------------------------------------------------------------------------


class _FakeRun:
    """Stands in for subprocess.run: records the call and returns a finished process."""

    def __init__(self, returncode: int) -> None:
        self.returncode = returncode
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        self.calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, self.returncode)


def test_install_chromium_runs_the_command_and_returns_its_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeRun(3)
    monkeypatch.setattr(browser.subprocess, "run", fake)
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert install_chromium(tmp_path) == 3
    ((command, kwargs),) = fake.calls
    assert command == install_command(tmp_path, frozen=False)[0]
    assert kwargs["check"] is False
    env = kwargs["env"]
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == str(browsers_dir(tmp_path))
    # The child keeps the rest of this process's environment (PATH and the like).
    assert env.get("PATH") == os.environ.get("PATH")


def test_install_chromium_uses_the_frozen_command_in_a_frozen_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeRun(0)
    monkeypatch.setattr(browser.subprocess, "run", fake)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert install_chromium(tmp_path) == 0
    ((command, _),) = fake.calls
    assert command == install_command(tmp_path, frozen=True)[0]


# --- the hidden entry that reaches Playwright's own command line --------------------------------


def _fake_playwright_main(
    monkeypatch: pytest.MonkeyPatch, exit_with: object, seen: list[list[str]]
) -> None:
    def main() -> None:
        seen.append(list(sys.argv))
        raise SystemExit(exit_with)

    monkeypatch.setattr(cli, "playwright_main", main)


def test_playwright_install_entry_runs_playwrights_main_with_the_rest_of_the_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[list[str]] = []
    _fake_playwright_main(monkeypatch, 4, seen)
    original_argv = list(sys.argv)
    code = cli.main(["_playwright-install", "install", "chromium", "--no-shell"])
    assert code == 4  # main() ends in sys.exit(code); cli.main keeps returning an int
    assert seen == [["playwright", "install", "chromium", "--no-shell"]]
    assert sys.argv == original_argv


@pytest.mark.parametrize(("exit_with", "code"), [(0, 0), (130, 130), (None, 0), ("failed", 1)])
def test_playwright_install_entry_turns_the_exit_into_an_int(
    monkeypatch: pytest.MonkeyPatch, exit_with: object, code: int
) -> None:
    _fake_playwright_main(monkeypatch, exit_with, [])
    assert cli.main(["_playwright-install", "install", "chromium"]) == code


def test_playwright_install_entry_hands_over_options_argparse_would_refuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # --no-shell and --version are Playwright's, not argparse's, so they pass straight through.
    seen: list[list[str]] = []
    _fake_playwright_main(monkeypatch, 0, seen)
    assert cli.main(["_playwright-install", "--version"]) == 0
    assert cli.main(["_playwright-install", "install", "chromium", "--no-shell"]) == 0
    assert seen == [
        ["playwright", "--version"],
        ["playwright", "install", "chromium", "--no-shell"],
    ]


@pytest.mark.parametrize(
    "rest",
    [
        [],
        ["install"],  # a bare install downloads every browser into Playwright's global cache
        ["install", "--with-deps"],
        ["install", "firefox"],
        ["install", "chromium", "firefox"],
        ["install", "chromium", "--with-deps"],
        ["install", "chromium", "--no-shell", "--force"],
        ["install", "--no-shell", "chromium"],
        ["install", "chromium", "--no-shell", "--no-shell"],
        ["install-deps"],
        ["uninstall", "--all"],
        ["--version", "install"],
        ["-V"],
        ["-h"],
        ["--help"],
        ["--no-such-option"],
        ["open", "https://example.invalid"],
    ],
)
def test_the_hidden_entry_refuses_anything_mihenk_does_not_need(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], rest: list[str]
) -> None:
    seen: list[list[str]] = []
    _fake_playwright_main(monkeypatch, 0, seen)
    code = cli.main(["_playwright-install", *rest])
    captured = capsys.readouterr()
    assert code == 2
    assert seen == []  # Playwright was not called
    assert captured.out == ""
    assert len(captured.err.strip().splitlines()) == 1
    assert "only 'install chromium [--no-shell]' and '--version'" in captured.err


def test_the_real_driver_answers_a_version_query_without_the_network() -> None:
    # `--version` asks the driver that ships in the wheel, and nothing else: no download, no
    # request. The suite's guard covers this process only, so the command is the proof.
    result = subprocess.run(
        [sys.executable, "-m", "mihenk", "_playwright-install", "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Version 1." in result.stdout


def test_playwright_install_entry_returns_when_main_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "playwright_main", lambda: None)
    assert cli.main(["_playwright-install", "install", "chromium"]) == 0


def test_the_hidden_entry_is_not_in_the_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--help"]) == 0
    out = capsys.readouterr().out
    assert "install-browser" in out
    assert "_playwright-install" not in out


# --- mihenk install-browser ---------------------------------------------------------------------


class _Install:
    """Stands in for install_chromium: counts the calls and returns an exit code.

    A run that exits 0 leaves a finished download behind, as Playwright does, unless `finishes`
    is False (a download that ended with 0 but never completed).
    """

    def __init__(self, code: int = 0, *, finishes: bool = True) -> None:
        self.code = code
        self.finishes = finishes
        self.folders: list[Path] = []

    def __call__(self, data_dir: Path) -> int:
        self.folders.append(data_dir)
        if self.code == 0 and self.finishes:
            _finished_download(data_dir)
        return self.code


def _answer(monkeypatch: pytest.MonkeyPatch, reply: str) -> list[str]:
    """Replaces input() with a fixed reply; returns the prompts it was shown."""
    prompts: list[str] = []

    def fake_input(prompt: str = "") -> str:
        prompts.append(prompt)
        return reply

    monkeypatch.setattr("builtins.input", fake_input)
    return prompts


@pytest.fixture
def install(monkeypatch: pytest.MonkeyPatch) -> _Install:
    fake = _Install()
    monkeypatch.setattr(cli, "install_chromium", fake)
    return fake


@pytest.mark.parametrize("reply", ["y", "Y", "yes", " y "])
def test_install_browser_runs_the_install_when_the_answer_is_yes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install: _Install, reply: str
) -> None:
    prompts = _answer(monkeypatch, reply)
    assert cli.main(["install-browser", "--data-dir", str(tmp_path)]) == 0
    assert install.folders == [tmp_path]
    (prompt,) = prompts
    assert prompt.startswith("Download Playwright's Chromium (about 200 MB) into ")
    assert str(browsers_dir(tmp_path)) in prompt
    assert "It is only needed if Chrome and Edge are not installed. [y/N]" in prompt


@pytest.mark.parametrize("reply", ["", "n", "N", "no", "maybe", "  "])
def test_install_browser_does_not_download_without_a_yes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    install: _Install,
    capsys: pytest.CaptureFixture[str],
    reply: str,
) -> None:
    _answer(monkeypatch, reply)
    assert cli.main(["install-browser", "--data-dir", str(tmp_path)]) == 0
    assert install.folders == []
    assert "Nothing was downloaded" in capsys.readouterr().out


def test_install_browser_counts_no_console_as_no(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install: _Install
) -> None:
    def no_console(prompt: str = "") -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", no_console)
    assert cli.main(["install-browser", "--data-dir", str(tmp_path)]) == 0
    assert install.folders == []


def test_install_browser_counts_a_missing_stdin_as_no(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install: _Install
) -> None:
    def lost_stdin(prompt: str = "") -> str:
        raise RuntimeError("input(): lost sys.stdin")  # a windowed build has no sys.stdin

    monkeypatch.setattr("builtins.input", lost_stdin)
    assert cli.main(["install-browser", "--data-dir", str(tmp_path)]) == 0
    assert install.folders == []


def test_a_folder_the_console_cannot_show_does_not_break_the_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install: _Install
) -> None:
    # A Windows user folder with Turkish letters, and a console whose code page has none of them.
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="ascii"))
    prompts = _answer(monkeypatch, "y")
    data_dir = tmp_path / "Ayşe Yılmaz"
    assert cli.main(["install-browser", "--data-dir", str(data_dir)]) == 0
    assert install.folders == [data_dir]
    (prompt,) = prompts
    prompt.encode("ascii")  # nothing in it is beyond the console's code page
    assert "Ay?e Y?lmaz" in prompt


def test_install_browser_yes_skips_the_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install: _Install
) -> None:
    def must_not_ask(prompt: str = "") -> str:
        raise AssertionError("--yes must not ask")

    monkeypatch.setattr("builtins.input", must_not_ask)
    assert cli.main(["install-browser", "--yes", "--data-dir", str(tmp_path)]) == 0
    assert install.folders == [tmp_path]


def test_done_is_said_after_a_finished_download(
    tmp_path: Path, install: _Install, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["install-browser", "--yes", "--data-dir", str(tmp_path)]) == 0
    captured = capsys.readouterr()
    assert "Done." in captured.out
    assert captured.err == ""
    assert has_downloaded_chromium(tmp_path)


def test_an_exit_code_of_0_without_a_finished_download_is_not_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = _Install(finishes=False)
    monkeypatch.setattr(cli, "install_chromium", fake)
    (browsers_dir(tmp_path) / "chromium-1243").mkdir(parents=True)  # started, never marked
    assert cli.main(["install-browser", "--yes", "--data-dir", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert fake.folders == [tmp_path]
    assert "Done" not in captured.out
    assert "did not finish" in captured.err
    assert len(captured.err.strip().splitlines()) == 1


def test_an_exit_code_of_0_with_nothing_downloaded_is_not_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "install_chromium", _Install(finishes=False))
    assert cli.main(["install-browser", "--yes", "--data-dir", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "Done" not in captured.out
    assert "did not finish" in captured.err


def test_a_failed_download_is_exit_code_1_and_says_so(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "install_chromium", _Install(code=7))
    assert cli.main(["install-browser", "--yes", "--data-dir", str(tmp_path)]) == 1
    assert "7" in capsys.readouterr().err


def test_a_download_that_cannot_start_is_exit_code_1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def cannot_start(data_dir: Path) -> int:
        raise OSError("no such program")

    monkeypatch.setattr(cli, "install_chromium", cannot_start)
    assert cli.main(["install-browser", "--yes", "--data-dir", str(tmp_path)]) == 1
    assert "no such program" in capsys.readouterr().err


def test_install_browser_with_no_data_dir_uses_the_default_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, install: _Install
) -> None:
    monkeypatch.setattr(cli, "default_data_dir", lambda: tmp_path)
    assert cli.main(["install-browser", "--yes"]) == 0
    assert install.folders == [tmp_path]


# --- capture: a downloaded Chromium is found ----------------------------------------------------


class _FakePlaywright:
    """Stands in for sync_playwright(): notes the environment at the moment it starts."""

    def __init__(self) -> None:
        self.browsers_path_at_start: str | None = None

    @contextmanager
    def __call__(self) -> Iterator[object]:
        self.browsers_path_at_start = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        yield object()


def test_capture_sets_the_browsers_folder_before_playwright_starts_and_allows_a_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "somewhere-else")
    fake_playwright = _FakePlaywright()
    monkeypatch.setattr(cli, "sync_playwright", fake_playwright)
    launches: list[dict[str, Any]] = []

    class _Browser:
        def close(self) -> None:
            launches.append({"closed": True})

    def fake_launch(pw: object, **kwargs: Any) -> browser.LaunchedBrowser:
        launches.append(kwargs)
        return browser.LaunchedBrowser("chromium", _Browser())  # type: ignore[arg-type]

    monkeypatch.setattr(cli, "launch_browser", fake_launch)
    monkeypatch.setattr(cli, "capture_page", lambda spec, ctx: [])
    ctx = SimpleNamespace(browser=None)
    results = cli._capture_in_browser(object(), ctx, tmp_path)  # type: ignore[arg-type]
    assert ctx.browser is not None  # the launched browser was handed to the capture
    assert results == []
    assert fake_playwright.browsers_path_at_start == str(browsers_dir(tmp_path))
    assert launches == [{"allow_downloaded": True}, {"closed": True}]
