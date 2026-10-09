import socket
import urllib.request

import pytest

from tests.helpers.site import LocalSite


def test_reaching_the_internet_is_blocked() -> None:
    with socket.socket() as sock, pytest.raises(RuntimeError, match="tried to reach"):
        sock.connect(("93.184.216.34", 80))


def test_loopback_is_allowed(site: LocalSite) -> None:
    site.add("/", "ok")
    with urllib.request.urlopen(site.url("/")) as response:  # noqa: S310 (a loopback test URL)
        assert response.read() == b"ok"
