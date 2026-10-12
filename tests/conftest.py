"""Shared fixtures. The whole test session, session-scoped fixtures included, runs behind a guard
that allows loopback connections only and refuses to look up any other host name."""

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
_real_getaddrinfo = socket.getaddrinfo


class NetworkBlocked(RuntimeError):
    pass


class _Attempts:
    """Every attempt the guard blocked, in order.

    Code under test can swallow `NetworkBlocked` with a broad `except Exception` and still pass,
    so each test also fails at teardown when an attempt happened during it.
    """

    def __init__(self) -> None:
        self._messages: list[str] = []
        self._reported = 0

    def block(self, message: str) -> NetworkBlocked:
        self._messages.append(message)
        return NetworkBlocked(message)

    def take(self) -> list[str]:
        """The attempts since the last call (session fixtures count toward the next test)."""
        fresh = self._messages[self._reported :]
        self._reported = len(self._messages)
        return fresh


_attempts = _Attempts()
_EXPECTED = pytest.StashKey[bool]()


def _check(sock: socket.socket, address: Any) -> None:
    if getattr(socket, "AF_UNIX", None) is not None and sock.family == socket.AF_UNIX:
        return
    host = address[0] if isinstance(address, tuple) else address
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise _attempts.block(f"a test tried to reach {host!r}") from None
    if not ip.is_loopback:
        raise _attempts.block(f"a test tried to reach {host}")


def _check_resolvable(host: Any) -> None:
    """Only IP literals and `localhost` may be looked up: any other name sends a DNS query."""
    if host is None or host == "":
        return
    name = host.decode("ascii", "replace") if isinstance(host, bytes) else str(host)
    if name.lower() == "localhost":
        return
    try:
        ipaddress.ip_address(name)
    except ValueError:
        raise _attempts.block(f"a test tried to resolve {name!r}") from None


def _guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
    _check_resolvable(host)
    return _real_getaddrinfo(host, *args, **kwargs)


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


def pytest_configure(config: pytest.Config) -> None:
    """Install the guard once for the whole run.

    The session-scoped fixtures (`pw`, `browser`) are set up before any function-scoped fixture,
    so a per-test guard would leave them unguarded.
    """
    patches = pytest.MonkeyPatch()
    config.add_cleanup(patches.undo)
    patches.setattr(socket, "getaddrinfo", _guarded_getaddrinfo)
    patches.setattr(socket.socket, "connect", _guarded_connect)
    patches.setattr(socket.socket, "connect_ex", _guarded_connect_ex)
    if sys.platform == "win32":
        patches.setattr(IocpProactor, "connect", _guarded_proactor_connect)


@pytest.fixture(autouse=True)
def _loopback_only(request: pytest.FixtureRequest) -> Iterator[None]:
    yield
    blocked = _attempts.take()
    if blocked and not request.node.stash.get(_EXPECTED, False):
        pytest.fail(
            "the network guard blocked an attempt that the test did not declare, so the error "
            "may have been swallowed (a broad `except Exception`). Fix the code, or add the "
            "`expect_blocked_network` fixture if the test blocks it on purpose: "
            + "; ".join(blocked),
            pytrace=False,
        )


@pytest.fixture
def expect_blocked_network(request: pytest.FixtureRequest) -> None:
    """Declare that this test blocks network attempts on purpose (the guard's own tests)."""
    request.node.stash[_EXPECTED] = True


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
