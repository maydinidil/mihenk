import asyncio
import os
import socket
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tests.helpers.site import LocalSite

ROOT = Path(__file__).resolve().parent.parent.parent


def test_reaching_the_internet_is_blocked(expect_blocked_network: None) -> None:
    with socket.socket() as sock, pytest.raises(RuntimeError, match="tried to reach"):
        sock.connect(("93.184.216.34", 80))


def test_asyncio_connections_are_blocked(expect_blocked_network: None) -> None:
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


def test_a_made_up_hostname_is_blocked_before_any_dns_query(
    expect_blocked_network: None,
) -> None:
    # .invalid is reserved (RFC 6761): it never resolves, so a leak would only show as a failure.
    with pytest.raises(RuntimeError, match="tried to resolve"):
        socket.getaddrinfo("no-such-host.invalid", 443)
    with pytest.raises(RuntimeError, match="tried to resolve"):
        socket.create_connection(("no-such-host.invalid", 443), timeout=2)


def test_localhost_and_numeric_hosts_still_resolve() -> None:
    # Numeric hosts need no DNS query; the connect guard then decides about them.
    assert socket.getaddrinfo("localhost", 80, type=socket.SOCK_STREAM)
    assert socket.getaddrinfo("127.0.0.1", 80, type=socket.SOCK_STREAM)
    assert socket.getaddrinfo("192.0.2.1", 80, type=socket.SOCK_STREAM)


@pytest.fixture(scope="session")
def session_scope_attempt() -> str:
    """Runs before any function-scoped fixture, as the session's `pw` and `browser` do."""
    try:
        socket.getaddrinfo("session.no-such-host.invalid", 443)
    except (OSError, RuntimeError) as exc:
        return type(exc).__name__
    return "resolved"


def test_session_scoped_fixtures_run_behind_the_guard(
    session_scope_attempt: str, expect_blocked_network: None
) -> None:
    assert session_scope_attempt == "NetworkBlocked"


INNER_TESTS = """
import socket

import pytest


def test_swallowed():
    try:
        socket.create_connection(("vendor.invalid", 443), timeout=1)
    except Exception:
        pass


def test_expected(expect_blocked_network):
    with pytest.raises(RuntimeError, match="tried to resolve"):
        socket.getaddrinfo("vendor.invalid", 443)


def test_clean():
    assert socket.getaddrinfo("127.0.0.1", 80)
"""


def test_a_swallowed_block_fails_its_test_and_an_expected_one_does_not(tmp_path: Path) -> None:
    # A real pytest run in a throwaway folder, with this repository's conftest as a plugin, so the
    # teardown check is seen failing a test. The folder holds only made-up .invalid hostnames.
    (tmp_path / "test_inner.py").write_text(INNER_TESTS, encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.conftest",
            "-p",
            "no:cacheprovider",
            "-c",
            str(tmp_path / "pytest.ini"),
            "--rootdir",
            str(tmp_path),
            "--color=no",
            "-rA",
            str(tmp_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    outcomes = set()
    for line in result.stdout.splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) > 1 and parts[0] in ("PASSED", "FAILED", "ERROR"):
            outcomes.add((parts[0], parts[1].split("::")[-1]))
    assert ("ERROR", "test_swallowed") in outcomes, result.stdout
    assert ("PASSED", "test_expected") in outcomes, result.stdout
    assert ("ERROR", "test_expected") not in outcomes, result.stdout
    assert ("PASSED", "test_clean") in outcomes, result.stdout
    assert ("ERROR", "test_clean") not in outcomes, result.stdout
    assert "expect_blocked_network" in result.stdout, result.stdout


PROXY_INNER_TESTS = """
import os
import subprocess
import sys
import urllib.request

import httpx2

from mihenk.capture.fetch import fetch_page, make_client

PROXY_NAMES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")


def test_the_proxy_variables_are_gone_and_no_proxy_is_everything():
    assert [name for name in PROXY_NAMES if os.environ.get(name)] == []
    assert os.environ["NO_PROXY"] == "*"
    # Python reads the registry on Windows only when there are no *_proxy variables at all.
    assert urllib.request.getproxies() == {"no": "*"}


def test_an_in_process_client_goes_direct(site):
    site.add("/page", "<p>direct</p>")
    with make_client("en") as client:
        assert fetch_page(client, site.url("/page")).html == "<p>direct</p>"
    with httpx2.Client() as plain:
        assert plain.get(site.url("/page")).text == "<p>direct</p>"


def test_a_child_process_goes_direct(site):
    site.add("/page", "<p>direct</p>")
    code = (
        "import sys, urllib.request\\n"
        "print(urllib.request.getproxies())\\n"
        "print(urllib.request.urlopen(sys.argv[1]).read().decode())\\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code, site.url("/page")],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines()[-1] == "<p>direct</p>"
"""


def test_a_proxy_on_the_machine_does_not_catch_the_tests_loopback_traffic(tmp_path: Path) -> None:
    # The outer environment has a proxy that nothing listens on (port 9): without the suite's
    # autouse fixture, every request to the test site would go there and fail.
    (tmp_path / "test_inner.py").write_text(PROXY_INNER_TESTS, encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    env = {**os.environ}
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        env[name] = "http://127.0.0.1:9"
        if sys.platform != "win32":  # Windows has one spelling of a variable
            env[name.lower()] = "http://127.0.0.1:9"
    env.pop("NO_PROXY", None)
    env.pop("no_proxy", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.conftest",
            "-p",
            "no:cacheprovider",
            "-c",
            str(tmp_path / "pytest.ini"),
            "--rootdir",
            str(tmp_path),
            "--color=no",
            "-rA",
            str(tmp_path),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    outcomes = {}
    for line in result.stdout.splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) > 1 and parts[0] in ("PASSED", "FAILED", "ERROR"):
            outcomes[parts[1].split("::")[-1]] = parts[0]
    assert outcomes == {
        "test_the_proxy_variables_are_gone_and_no_proxy_is_everything": "PASSED",
        "test_an_in_process_client_goes_direct": "PASSED",
        "test_a_child_process_goes_direct": "PASSED",
    }, result.stdout
