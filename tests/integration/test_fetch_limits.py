"""The time and size bounds of the two fetches: a deadline for the whole request, and redirect
bodies that are never read. Mock transports answer the cases that need a body counted; the
trickle test uses a real socket on 127.0.0.1."""

import inspect
import threading
import time
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx2
import pytest

from mihenk.capture.fetch import (
    PAGE_DEADLINE_S,
    ROBOTS_DEADLINE_S,
    FetchFailure,
    fetch_page,
    fetch_robots,
    make_client,
)
from mihenk.capture.models import CaptureStatus
from mihenk.capture.robots import MAX_REDIRECTS, RobotsFetch, decide
from tests.helpers.site import LocalSite

BASE = "http://pages.test"  # never resolved: a MockTransport answers
CHUNK = b"x" * 65536
PAGE = "<p>€5</p>".encode()
HTML = {"Content-Type": "text/html; charset=utf-8"}


class Body:
    """A body made of equal chunks that counts how many were read.

    `limit` ends the body (a huge one is finite so that a regression cannot eat the machine);
    `guard` raises instead once that many chunks were read, for a body that must never be read.
    """

    def __init__(self, *, limit: int, pause_s: float = 0.0, guard: int | None = None) -> None:
        self.limit = limit
        self.pause_s = pause_s
        self.guard = guard
        self.served = 0

    def chunks(self) -> Iterator[bytes]:
        while self.served < self.limit:
            if self.guard is not None and self.served >= self.guard:
                raise AssertionError("the body was read although it must not be")
            if self.pause_s:
                time.sleep(self.pause_s)
            self.served += 1
            yield CHUNK


def _client(handler: Callable[[httpx2.Request], httpx2.Response]) -> httpx2.Client:
    return httpx2.Client(transport=httpx2.MockTransport(handler), follow_redirects=True)


def _never_read() -> Body:
    return Body(limit=1_000_000, guard=0)


def _redirect(body: Body, to: str = f"{BASE}/new") -> httpx2.Response:
    return httpx2.Response(302, headers={"Location": to}, content=body.chunks())


def test_default_deadlines() -> None:
    assert (PAGE_DEADLINE_S, ROBOTS_DEADLINE_S) == (90.0, 30.0)
    assert inspect.signature(fetch_page).parameters["deadline_s"].default == PAGE_DEADLINE_S
    assert inspect.signature(fetch_robots).parameters["deadline_s"].default == ROBOTS_DEADLINE_S


# The deadline.


def test_trickling_page_hits_the_deadline() -> None:
    body = Body(limit=100, pause_s=0.05)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, headers=HTML, content=body.chunks())

    started = time.monotonic()
    with _client(handler) as client, pytest.raises(FetchFailure) as caught:
        fetch_page(client, f"{BASE}/slow", deadline_s=0.3)
    assert caught.value.status is CaptureStatus.TIMEOUT
    assert "deadline" in caught.value.detail
    assert time.monotonic() - started < 3
    assert body.served < 40


def test_trickling_robots_hits_the_deadline() -> None:
    body = Body(limit=100, pause_s=0.05)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=body.chunks())

    with _client(handler) as client:
        fetched = fetch_robots(client, f"{BASE}/robots.txt", deadline_s=0.3)
    assert fetched == RobotsFetch(None, None, "unreachable: deadline passed")
    assert not decide(fetched, f"{BASE}/pricing").allowed
    assert body.served < 40


class _Trickle(BaseHTTPRequestHandler):
    """Sends the headers of a long page, then one byte every 0.3 s."""

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", "100000")
        self.end_headers()
        try:
            for _ in range(20):  # ends after 6 s, so a missing deadline fails instead of hanging
                self.wfile.write(b"x")
                time.sleep(0.3)
        except OSError:
            return  # the client gave up

    def log_message(self, format: str, *args: object) -> None:
        return


def test_a_real_server_trickling_one_byte_at_a_time_is_cut_off() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Trickle)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        started = time.monotonic()
        # Each read is under the 0.5 s timeout, so only the deadline can stop this.
        with make_client("en", timeout_s=0.5) as client, pytest.raises(FetchFailure) as caught:
            fetch_page(client, url, deadline_s=1.0)
        elapsed = time.monotonic() - started
    finally:
        server.shutdown()
        server.server_close()
    assert caught.value.status is CaptureStatus.TIMEOUT
    assert "deadline" in caught.value.detail
    assert 0.9 < elapsed < 4


def test_the_deadline_is_checked_before_every_request(site: LocalSite) -> None:
    site.add("/page", "<p>x</p>")
    with make_client("en") as client:
        with pytest.raises(FetchFailure) as caught:
            fetch_page(client, site.url("/page"), deadline_s=-1)
        fetched = fetch_robots(client, site.url("/page"), deadline_s=-1)
    assert caught.value.status is CaptureStatus.TIMEOUT
    assert fetched == RobotsFetch(None, None, "unreachable: deadline passed")
    assert site.hits == []


def test_a_slow_redirect_chain_hits_the_deadline_before_its_end() -> None:
    requests: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request.url.path)
        time.sleep(0.1)
        hop = int(request.url.path.removeprefix("/hop"))
        if hop < MAX_REDIRECTS:
            return httpx2.Response(302, headers={"Location": f"{BASE}/hop{hop + 1}"})
        return httpx2.Response(200, headers=HTML, content=PAGE)

    with _client(handler) as client, pytest.raises(FetchFailure) as caught:
        fetch_page(client, f"{BASE}/hop0", deadline_s=0.25)
    assert caught.value.status is CaptureStatus.TIMEOUT
    assert "deadline" in caught.value.detail
    assert len(requests) < MAX_REDIRECTS + 1

    requests.clear()
    with _client(handler) as client:
        fetched = fetch_robots(client, f"{BASE}/hop0", deadline_s=0.25)
    assert fetched == RobotsFetch(None, None, "unreachable: deadline passed")
    assert len(requests) < MAX_REDIRECTS + 1


def test_a_fast_fetch_is_not_touched_by_the_deadline(site: LocalSite) -> None:
    site.add("/page", "<p>x</p>")
    with make_client("en") as client:
        assert fetch_page(client, site.url("/page"), deadline_s=30).html == "<p>x</p>"
        assert fetch_robots(client, site.url("/page"), deadline_s=30).status == 200


# Redirect bodies are never read.


def _handler_for(old: Callable[[], httpx2.Response]) -> Callable[[httpx2.Request], httpx2.Response]:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/old":
            return old()
        return httpx2.Response(200, headers=HTML, content=PAGE)

    return handler


def test_an_endless_redirect_body_is_never_read_by_fetch_page() -> None:
    body = _never_read()
    with _client(_handler_for(lambda: _redirect(body))) as client:
        page = fetch_page(client, f"{BASE}/old")
    assert body.served == 0
    assert page.status == 200
    assert page.html == "<p>€5</p>"
    assert page.url == f"{BASE}/old"
    assert page.final_url == f"{BASE}/new"


def test_an_endless_redirect_body_is_never_read_by_fetch_robots() -> None:
    body = _never_read()
    with _client(_handler_for(lambda: _redirect(body))) as client:
        fetched = fetch_robots(client, f"{BASE}/old")
    assert body.served == 0
    assert fetched == RobotsFetch(200, PAGE, "fetched")


def test_a_large_redirect_body_is_followed_without_being_read() -> None:
    body = Body(limit=640)  # 40 MiB, far over both caps
    with _client(_handler_for(lambda: _redirect(body))) as client:
        page = fetch_page(client, f"{BASE}/old")
        fetched = fetch_robots(client, f"{BASE}/old")
    assert body.served == 0
    assert page.final_url == f"{BASE}/new"
    assert fetched.status == 200


def test_a_large_redirect_body_from_a_real_server_is_followed(site: LocalSite) -> None:
    site.add("/old", b"r" * (40 * 1024 * 1024), status=301, headers={"Location": "/new"})
    site.add("/new", "<p>€5</p>")
    started = time.monotonic()
    with make_client("en") as client:
        page = fetch_page(client, site.url("/old"))
    assert page.final_url == site.url("/new")
    assert page.html == "<p>€5</p>"
    assert time.monotonic() - started < 5


# The redirect limit still holds, and it holds without reading anything.


def _chain(bodies: list[Body], requests: list[str]) -> Callable[[httpx2.Request], httpx2.Response]:
    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request.url.path)
        hop = int(request.url.path.removeprefix("/hop"))
        if hop < len(bodies):
            return _redirect(bodies[hop], f"{BASE}/hop{hop + 1}")
        return httpx2.Response(200, headers=HTML, content=PAGE)

    return handler


def test_the_sixth_redirect_fails_without_a_seventh_request_or_a_read() -> None:
    bodies = [_never_read() for _ in range(MAX_REDIRECTS + 3)]
    requests: list[str] = []
    with _client(_chain(bodies, requests)) as client, pytest.raises(FetchFailure) as caught:
        fetch_page(client, f"{BASE}/hop0")
    assert caught.value.status is CaptureStatus.HTTP_ERROR
    assert caught.value.detail == f"more than {MAX_REDIRECTS} redirects"
    assert requests == [f"/hop{n}" for n in range(MAX_REDIRECTS + 1)]
    assert [body.served for body in bodies] == [0] * len(bodies)

    requests.clear()
    with _client(_chain(bodies, requests)) as client:
        fetched = fetch_robots(client, f"{BASE}/hop0")
    assert fetched == RobotsFetch(None, None, f"unreachable: more than {MAX_REDIRECTS} redirects")
    assert requests == [f"/hop{n}" for n in range(MAX_REDIRECTS + 1)]


def test_five_redirects_are_followed_and_the_last_url_is_reported() -> None:
    bodies = [_never_read() for _ in range(MAX_REDIRECTS)]
    requests: list[str] = []
    with _client(_chain(bodies, requests)) as client:
        page = fetch_page(client, f"{BASE}/hop0")
    assert page.final_url == f"{BASE}/hop{MAX_REDIRECTS}"
    assert page.url == f"{BASE}/hop0"
    assert page.html == "<p>€5</p>"
    assert len(requests) == MAX_REDIRECTS + 1


def test_redirect_hits_on_a_real_site(site: LocalSite) -> None:
    for hop in range(MAX_REDIRECTS + 2):
        site.redirect(f"/hop{hop}", f"/hop{hop + 1}")
    with make_client("en") as client:
        with pytest.raises(FetchFailure):
            fetch_page(client, site.url("/hop0"))
        assert fetch_robots(client, site.url("/hop0")).status is None
    expected = [f"/hop{n}" for n in range(MAX_REDIRECTS + 1)]
    assert site.hits == expected + expected


def test_a_redirect_without_a_location_is_the_final_response() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(304, headers=HTML)

    with _client(handler) as client:
        page = fetch_page(client, f"{BASE}/same")
        fetched = fetch_robots(client, f"{BASE}/same")
    assert page.status == 304
    assert page.final_url == f"{BASE}/same"
    assert fetched.status == 304
