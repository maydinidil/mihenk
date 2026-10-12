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
from typing import Any

from playwright.sync_api import Browser, Playwright
from playwright.sync_api import Error as PlaywrightError

CHANNEL_ORDER: tuple[str, ...] = ("chrome", "msedge")
# The tests set this to 1; a user who sets it gets a browser that reaches nothing but this
# machine: every name except 127.0.0.1 fails to resolve, and the proxy is a dead port.
LOOPBACK_ONLY_VARIABLE = "MIHENK_BROWSER_LOOPBACK_ONLY"
_LOOPBACK_ONLY_RULES = "MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"
_LOOPBACK_ONLY_PROXY: dict[str, str] = {"server": "http://127.0.0.1:9", "bypass": "127.0.0.1"}

# The browser's own services, which reach Google or Microsoft by themselves while mihenk uses the
# browser, stay off (decision 0007, measured on Chrome 154 and Edge 155). Every launch gets this,
# confined or not. The first two are Playwright defaults too, kept here so the promise does not
# rest on Playwright's list. The two URL switches point the browser's own account check and
# component updater at port 9 on this machine, a port Chrome refuses for web requests
# (ERR_UNSAFE_PORT), so those requests end inside the browser. Pages that load
# accounts.google.com are not touched: the switch changes only the browser's own address for it.
_OWN_SWITCHES: tuple[str, ...] = (
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-sync",
    "--disable-domain-reliability",
    "--no-pings",
    "--allow-browser-signin=false",
    "--gaia-url=http://127.0.0.1:9/",
    "--component-updater=url-source=http://127.0.0.1:9/",
)
_OWN_DISABLED_FEATURES: tuple[str, ...] = (
    "NetworkTimeServiceQuerying",  # the clock check (Google's and Edge's time servers)
    "SafeBrowsingHashPrefixRealTimeLookups",  # the Safe Browsing key fetch at start
    "AimEnabled",  # Google's AI Mode check (www.google.com/async/folae)
    "PreconnectToSearch",  # the early connection to the default search engine
    "msImplicitSignin",  # Edge: signing in with the Windows account, and what follows it
    "msUXConfigService",  # Edge: the configuration service (serviceexperimentation)
    "msUXConfigServiceV3",
    "msEdgeMouseGestureSupported",  # Edge: the mouse gesture configuration download
)
# Services with no switch: their own host names, which no web page loads, do not resolve. Push
# messaging (GCM) in Chrome, and Edge's service host (its ad blocklist has no switch).
_SERVICE_HOSTS_WITHOUT_SWITCH: tuple[str, ...] = (
    "android.clients.google.com",
    "mtalk.google.com",
    "edge.microsoft.com",
)
# Playwright passes this `--disable-features` list itself (Playwright 1.63, `chromiumSwitches.ts`
# in its driver). Chrome keeps only the last `--disable-features` on a command line, so the launch
# leaves Playwright's switch out by its exact text and passes one switch with both lists. A test
# reads the real browser's command line and fails when Playwright's list changes.
_PLAYWRIGHT_DISABLED_FEATURES: tuple[str, ...] = (
    "AvoidUnnecessaryBeforeUnloadCheckSync",
    "DestroyProfileOnBrowserClose",
    "DialMediaRouteProvider",
    "GlobalMediaControls",
    "HttpsUpgrades",
    "LensOverlay",
    "MediaRouter",
    "PaintHolding",
    "ThirdPartyStoragePartitioning",
    "BlockOriginHeaderModificationOnRedirect",
    "Translate",
    "AutoDeElevate",
    "OptimizationHints",
    "msForceBrowserSignIn",
    "msEdgeUpdateLaunchServicesPreferredVersion",
)
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


def _launch_options(loopback_only: bool) -> dict[str, Any]:
    """What every launch passes besides channel and headless (decision 0007).

    With `loopback_only` the tests' confinement joins the services' own host rules in the one
    `--host-resolver-rules` switch (Chrome keeps only the last), and a dead proxy is added.
    """
    rules = [f"MAP {host} ~NOTFOUND" for host in _SERVICE_HOSTS_WITHOUT_SWITCH]
    if loopback_only:
        rules.append(_LOOPBACK_ONLY_RULES)
    playwright_features = "--disable-features=" + ",".join(_PLAYWRIGHT_DISABLED_FEATURES)
    options: dict[str, Any] = {
        "args": [
            *_OWN_SWITCHES,
            playwright_features + "," + ",".join(_OWN_DISABLED_FEATURES),
            "--host-resolver-rules=" + " , ".join(rules),
        ],
        "ignore_default_args": [playwright_features],
    }
    if loopback_only:
        options["proxy"] = dict(_LOOPBACK_ONLY_PROXY)
    return options


def launch_browser(
    pw: Playwright, *, headless: bool = True, allow_downloaded: bool = False
) -> LaunchedBrowser:
    tried: list[str] = []
    channels = CHANNEL_ORDER + (("chromium",) if allow_downloaded else ())
    options = _launch_options(os.environ.get(LOOPBACK_ONLY_VARIABLE) == "1")
    for channel in channels:
        try:
            return LaunchedBrowser(
                channel, pw.chromium.launch(channel=channel, headless=headless, **options)
            )
        except PlaywrightError as exc:
            if _NOT_FOUND not in str(exc) and "Executable doesn't exist" not in str(exc):
                raise
            tried.append(channel)
    raise BrowserUnavailable(tried)


def browsers_dir(data_dir: Path) -> Path:
    """Where a downloaded Chromium lives: inside the data folder, not Playwright's own default."""
    return data_dir / "browsers"


# The empty file that Playwright's downloader writes into a browser's folder after it has
# extracted the whole archive, and that its own registry looks for to tell a finished download
# from a half one. Checked against Playwright 1.63: `INSTALLATION_COMPLETE` in
# `playwright/driver/package/lib/coreBundle.js` (the downloader's `browserDirectoryToMarkerFilePath`),
# and present in a real `chromium-1243` folder.
_INSTALLATION_COMPLETE = "INSTALLATION_COMPLETE"


def has_downloaded_chromium(data_dir: Path) -> bool:
    """Whether the browsers folder holds a finished Chromium (`chromium-<revision>`) download.

    A folder counts only when Playwright marked it complete: a download that stopped half way
    leaves the folder without the mark. The headless shell (`chromium_headless_shell-*`) does
    not count. A revision from an older Playwright counts too, so this says that a download was
    made, not that this Playwright can launch it.
    """
    folder = browsers_dir(data_dir)
    if not folder.is_dir():
        return False
    return any((path / _INSTALLATION_COMPLETE).is_file() for path in folder.glob("chromium-*"))


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
