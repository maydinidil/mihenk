"""Finding a browser to drive (design §17): installed Chrome, then installed Edge.

Playwright's own Chromium comes last and only after the user agreed to download it: it goes into
the `browsers` folder of the app's data folder, and `start_playwright_env` points Playwright there.
Playwright is not thread-safe: everything here runs on the one capture thread.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Browser, Playwright
from playwright.sync_api import Error as PlaywrightError

CHANNEL_ORDER: tuple[str, ...] = ("chrome", "msedge")
# Playwright reports a missing branded browser with this phrase. It is not documented API
# (checked against Playwright 1.63's source, §22), so a test pins it.
_NOT_FOUND = "is not found at"


class BrowserUnavailable(Exception):
    def __init__(self, tried: Sequence[str]) -> None:
        super().__init__("No usable browser found. Tried: " + ", ".join(tried))
        self.tried = tuple(tried)


@dataclass(frozen=True)
class LaunchedBrowser:
    channel: str
    browser: Browser


def launch_browser(
    pw: Playwright, *, headless: bool = True, allow_downloaded: bool = False
) -> LaunchedBrowser:
    tried: list[str] = []
    channels = CHANNEL_ORDER + (("chromium",) if allow_downloaded else ())
    for channel in channels:
        try:
            return LaunchedBrowser(channel, pw.chromium.launch(channel=channel, headless=headless))
        except PlaywrightError as exc:
            if _NOT_FOUND not in str(exc) and "Executable doesn't exist" not in str(exc):
                raise
            tried.append(channel)
    raise BrowserUnavailable(tried)


def browsers_dir(data_dir: Path) -> Path:
    """Where a downloaded Chromium lives: inside the data folder, not Playwright's own default."""
    return data_dir / "browsers"


def has_downloaded_chromium(data_dir: Path) -> bool:
    """Whether the browsers folder holds a Chromium (`chromium-<revision>`) of any revision.

    The headless shell (`chromium_headless_shell-*`) does not count. A revision from an older
    Playwright counts too, so this says that a download was made, not that this Playwright can
    launch it.
    """
    folder = browsers_dir(data_dir)
    if not folder.is_dir():
        return False
    return any(path.is_dir() for path in folder.glob("chromium-*"))


def start_playwright_env(data_dir: Path) -> None:
    """Points Playwright at the data folder's browsers. Call it before `sync_playwright()` starts.

    The driver process reads `PLAYWRIGHT_BROWSERS_PATH` when it starts, and the setting is for the
    whole process, so a program that does this keeps it for the rest of its life.
    """
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_dir(data_dir))


def install_command(data_dir: Path, frozen: bool) -> tuple[list[str], dict[str, str]]:
    """The command that downloads Chromium, and the environment it needs on top of this one's.

    Playwright's command line is reached through mihenk's own hidden `_playwright-install`
    command, so the same program installs the browser it will launch. Run from source that is
    `python -m mihenk`; a frozen app has no `-m`, its executable takes the command directly.
    `--no-shell` leaves out the separate headless shell (about 100 MB), which is never launched:
    the downloaded browser is started with `channel="chromium"`.
    """
    entry = [sys.executable] if frozen else [sys.executable, "-m", "mihenk"]
    command = [*entry, "_playwright-install", "install", "chromium", "--no-shell"]
    return command, {"PLAYWRIGHT_BROWSERS_PATH": str(browsers_dir(data_dir))}


def install_chromium(data_dir: Path) -> int:
    """Downloads Playwright's Chromium (about 200 MB) into the data folder; returns the exit code.

    The caller has the user's consent. The download's own progress shows on this process's console.
    """
    command, env = install_command(data_dir, frozen=bool(getattr(sys, "frozen", False)))
    return subprocess.run(command, env={**os.environ, **env}, check=False).returncode
