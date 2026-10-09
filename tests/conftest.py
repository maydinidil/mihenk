"""Shared fixtures. Every test runs behind a guard that allows loopback connections only."""

from __future__ import annotations

import ipaddress
import os
import socket
import sys
from collections.abc import Iterator
from typing import Any

import pytest

from tests.helpers.site import LocalSite

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


class NetworkBlocked(RuntimeError):
    pass


def _check(sock: socket.socket, address: Any) -> None:
    if getattr(socket, "AF_UNIX", None) is not None and sock.family == socket.AF_UNIX:
        return
    host = address[0] if isinstance(address, tuple) else address
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise NetworkBlocked(f"a test tried to reach {host!r}") from None
    if not ip.is_loopback:
        raise NetworkBlocked(f"a test tried to reach {host}")


def _guarded_connect(self: socket.socket, address: Any) -> None:
    _check(self, address)
    _real_connect(self, address)


def _guarded_connect_ex(self: socket.socket, address: Any) -> int:
    _check(self, address)
    return _real_connect_ex(self, address)


if sys.platform == "win32":
    # Windows' default asyncio loop connects through the IOCP proactor (ConnectEx), which never
    # calls socket.connect, so it needs its own guard.
    from asyncio.windows_events import IocpProactor

    _real_proactor_connect = IocpProactor.connect

    def _guarded_proactor_connect(self: IocpProactor, conn: socket.socket, address: Any) -> Any:
        _check(conn, address)
        return _real_proactor_connect(self, conn, address)


@pytest.fixture(autouse=True)
def _loopback_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _guarded_connect_ex)
    if sys.platform == "win32":
        monkeypatch.setattr(IocpProactor, "connect", _guarded_proactor_connect)


@pytest.fixture
def site() -> Iterator[LocalSite]:
    with LocalSite() as running:
        yield running


@pytest.fixture(scope="session")
def pw() -> Iterator[Any]:
    """The one Playwright session of the test run: the sync API allows one per thread."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as session:
        yield session


@pytest.fixture(scope="session")
def browser(pw: Any) -> Iterator[Any]:
    from mihenk.capture.browser import BrowserUnavailable, launch_browser

    try:
        launched = launch_browser(pw)
    except BrowserUnavailable as exc:
        if os.environ.get("MIHENK_REQUIRE_BROWSER") == "1":
            pytest.fail(str(exc))
        pytest.skip(str(exc))
    yield launched
    launched.browser.close()
