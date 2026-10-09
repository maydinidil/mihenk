"""Finding a browser to drive (design §17): installed Chrome, then installed Edge.

Playwright's own Chromium is used only after the user agreed to download it (Task 1.10).
Playwright is not thread-safe: everything here runs on the one capture thread.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

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
