import gzip
import socket
from collections.abc import Iterator

import httpx2
import pytest

from mihenk.capture.fetch import fetch_robots, make_client
from mihenk.capture.robots import (
    MAX_REDIRECTS,
    MAX_ROBOTS_BYTES,
    RobotsFetch,
    RobotsGate,
    decide,
)
from tests.helpers.site import LocalSite

RULES = b"User-agent: *\nDisallow: /pricing\n"


def test_robots_redirect_loop_disallows(site: LocalSite) -> None:
    site.redirect("/robots.txt", "/robots-a")
    site.redirect("/robots-a", "/robots-b")
    site.redirect("/robots-b", "/robots-a")
    with make_client("en") as client:
        fetched = fetch_robots(client, site.url("/robots.txt"))
    assert fetched.status is None
    assert fetched.body is None
    assert fetched.detail == "unreachable: more than 5 redirects"
    assert not decide(fetched, site.url("/pricing")).allowed


def test_robots_redirect_is_followed(site: LocalSite) -> None:
    site.redirect("/robots.txt", "/real-robots.txt")
    site.add("/real-robots.txt", "User-agent: *\nDisallow: /pricing\n", content_type="text/plain")
    with make_client("en") as client:
        gate = RobotsGate(lambda url: fetch_robots(client, url))
        assert not gate.check(site.url("/pricing")).allowed
        assert gate.check(site.url("/about")).allowed


def test_missing_robots_allows(site: LocalSite) -> None:
    with make_client("en") as client:
        assert decide(fetch_robots(client, site.url("/robots.txt")), site.url("/x")).allowed


def test_five_redirects_are_followed_and_six_are_not(site: LocalSite) -> None:
    for hop in range(MAX_REDIRECTS + 1):
        site.redirect(f"/r{hop}", f"/r{hop + 1}")
    site.add(f"/r{MAX_REDIRECTS + 1}", RULES, content_type="text/plain")
    with make_client("en") as client:
        five = fetch_robots(client, site.url("/r1"))  # r1 to r6 is 5 hops, then the file
        six = fetch_robots(client, site.url("/r0"))  # 6 hops
    assert five == RobotsFetch(200, RULES, "fetched")
    assert six == RobotsFetch(None, None, "unreachable: more than 5 redirects")


def test_status_and_body_are_passed_through(site: LocalSite) -> None:
    site.add("/robots.txt", RULES, content_type="text/plain")
    site.add("/forbidden/robots.txt", "no", status=403)
    with make_client("en") as client:
        ok = fetch_robots(client, site.url("/robots.txt"))
        forbidden = fetch_robots(client, site.url("/forbidden/robots.txt"))
    assert ok == RobotsFetch(200, RULES, "fetched")
    assert forbidden.status == 403
    assert not decide(forbidden, site.url("/y")).allowed


def test_robots_body_is_cut_at_the_limit_and_the_rules_before_it_apply(site: LocalSite) -> None:
    filler = b"# padding\n" * (3 * MAX_ROBOTS_BYTES // 10)  # three times the limit
    site.add("/robots.txt", RULES + filler + b"User-agent: *\nDisallow: /late\n")
    with make_client("en") as client:
        fetched = fetch_robots(client, site.url("/robots.txt"))
    assert fetched.status == 200
    assert fetched.body is not None
    assert len(fetched.body) == MAX_ROBOTS_BYTES
    assert fetched.body.startswith(RULES)
    assert not decide(fetched, site.url("/pricing")).allowed
    assert decide(fetched, site.url("/late")).allowed  # past the limit, so never read


def test_reading_stops_at_the_limit_instead_of_loading_the_whole_body() -> None:
    chunk = b"# padding\n" * 6400  # 64,000 bytes
    served = 0

    def endless() -> Iterator[bytes]:
        nonlocal served
        while served < 200:  # 12.8 MB, 25 times the limit, if anyone read it all
            served += 1
            yield chunk

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=endless())

    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        fetched = fetch_robots(client, "http://robots.test/robots.txt")
    assert fetched.status == 200
    assert fetched.body is not None
    assert len(fetched.body) == MAX_ROBOTS_BYTES
    assert served <= MAX_ROBOTS_BYTES // len(chunk) + 2


def test_robots_timeout_is_unreachable(site: LocalSite) -> None:
    site.add("/robots.txt", "User-agent: *\nAllow: /\n", content_type="text/plain", delay_s=2)
    with make_client("en", timeout_s=0.5) as client:
        fetched = fetch_robots(client, site.url("/robots.txt"))
    assert fetched.status is None
    assert fetched.body is None
    assert fetched.detail.startswith("unreachable: ")
    assert "Timeout" in fetched.detail
    assert not decide(fetched, site.url("/pricing")).allowed


def test_robots_refused_connection_is_unreachable() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with make_client("en") as client:
        fetched = fetch_robots(client, f"http://127.0.0.1:{port}/robots.txt")
    assert fetched.status is None
    assert fetched.body is None
    assert fetched.detail.startswith("unreachable: ")
    assert not decide(fetched, f"http://127.0.0.1:{port}/pricing").allowed


def test_robots_with_a_corrupt_body_is_unreachable(site: LocalSite) -> None:
    # Claims gzip but is not gzip: reading the body fails after the status line was read.
    site.add(
        "/robots.txt",
        RULES,
        content_type="text/plain",
        headers={"Content-Encoding": "gzip"},
    )
    with make_client("en") as client:
        fetched = fetch_robots(client, site.url("/robots.txt"))
    assert fetched.status is None
    assert fetched.body is None
    assert fetched.detail.startswith("unreachable: ")
    assert not decide(fetched, site.url("/pricing")).allowed


def test_robots_gzip_is_decoded(site: LocalSite) -> None:
    site.add(
        "/robots.txt",
        gzip.compress(RULES),
        content_type="text/plain",
        headers={"Content-Encoding": "gzip"},
    )
    with make_client("en") as client:
        fetched = fetch_robots(client, site.url("/robots.txt"))
    assert fetched == RobotsFetch(200, RULES, "fetched")


def test_robots_failures_never_raise_into_the_gate() -> None:
    def broken(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadError("connection reset", request=request)

    def unsupported(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.UnsupportedProtocol("no scheme", request=request)

    def corrupt(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.DecodingError("bad gzip", request=request)

    def bad_host(request: httpx2.Request) -> httpx2.Response:
        raise UnicodeError("label empty or too long")  # what the socket layer raises for a..b

    for handler in (broken, unsupported, corrupt, bad_host):
        with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
            gate = RobotsGate(lambda url, client=client: fetch_robots(client, url))
            decision = gate.check("http://robots.test/pricing")
        assert not decision.allowed
        assert "unreachable" in decision.reason


@pytest.mark.parametrize(
    "url", ["http://", "http://[::1", "http://127.0.0.1:abc/robots.txt", "ftp://robots.test/"]
)
def test_robots_url_that_cannot_be_requested_does_not_raise(url: str) -> None:
    with make_client("en") as client:
        fetched = fetch_robots(client, url)
    assert fetched.status is None
    assert fetched.detail.startswith("unreachable: ")
