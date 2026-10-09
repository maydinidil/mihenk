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
from typing import Any

import pytest

from mihenk import cli
from mihenk.capture import browser
from mihenk.capture.browser import (
    browsers_dir,
    has_downloaded_chromium,
    install_chromium,
    install_command,
    start_playwright_env,
)

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
    (browsers_dir(tmp_path) / "chromium-1243").mkdir(parents=True)
    assert has_downloaded_chromium(tmp_path)


def test_an_empty_browsers_folder_has_no_chromium(tmp_path: Path) -> None:
    browsers_dir(tmp_path).mkdir()
    assert not has_downloaded_chromium(tmp_path)


def test_the_headless_shell_and_other_browsers_are_not_a_chromium(tmp_path: Path) -> None:
    for name in ("chromium_headless_shell-1243", "ffmpeg-1011", "firefox-1500"):
        (browsers_dir(tmp_path) / name).mkdir(parents=True)
    assert not has_downloaded_chromium(tmp_path)


def test_a_file_called_chromium_is_not_a_download(tmp_path: Path) -> None:
    browsers_dir(tmp_path).mkdir()
    (browsers_dir(tmp_path) / "chromium-1243").write_text("not a folder", encoding="utf-8")
    assert not has_downloaded_chromium(tmp_path)


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
    seen: list[list[str]] = []
    _fake_playwright_main(monkeypatch, 0, seen)
    assert cli.main(["_playwright-install", "--no-such-option", "-h"]) == 0
    assert seen == [["playwright", "--no-such-option", "-h"]]


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
    """Stands in for install_chromium: counts the calls and returns an exit code."""

    def __init__(self, code: int = 0) -> None:
        self.code = code
        self.folders: list[Path] = []

    def __call__(self, data_dir: Path) -> int:
        self.folders.append(data_dir)
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
