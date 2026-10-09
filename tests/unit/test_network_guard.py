import asyncio
import socket
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.helpers.site import LocalSite


def test_reaching_the_internet_is_blocked() -> None:
    with socket.socket() as sock, pytest.raises(RuntimeError, match="tried to reach"):
        sock.connect(("93.184.216.34", 80))


def test_asyncio_connections_are_blocked() -> None:
    # Windows' default event loop connects through the IOCP proactor, not socket.connect.
    # 192.0.2.1 is a documentation address (RFC 5737): no real host answers it. The loop runs
    # on its own thread because the session's Playwright keeps a loop running on this one.
    async def attempt() -> None:
        await asyncio.wait_for(asyncio.open_connection("192.0.2.1", 80), timeout=2)

    with (
        ThreadPoolExecutor(max_workers=1) as pool,
        pytest.raises(RuntimeError, match="tried to reach"),
    ):
        pool.submit(lambda: asyncio.run(attempt())).result()


def test_loopback_is_allowed(site: LocalSite) -> None:
    site.add("/", "ok")
    with urllib.request.urlopen(site.url("/")) as response:  # noqa: S310 (a loopback test URL)
        assert response.read() == b"ok"
