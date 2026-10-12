import gzip

import httpx2
import pytest

from mihenk import __version__
from mihenk.capture.fetch import (
    KEPT_HEADERS,
    MAX_PAGE_BYTES,
    FetchFailure,
    _timeout_detail,
    fetch_page,
    make_client,
)
from mihenk.capture.models import CaptureStatus
from mihenk.capture.robots import MAX_REDIRECTS
from tests.helpers.pages import PAGES_DIR, load_expectations, serve_page
from tests.helpers.site import LocalSite


def test_static_table_is_fetched(site: LocalSite) -> None:
    url = serve_page(site, "static-table")
    with make_client("en") as client:
        page = fetch_page(client, url)
    assert page.status == 200
    assert page.url == url
    assert page.final_url == url
    assert page.encoding == "utf-8"
    assert page.raw == (PAGES_DIR / "static-table" / "page.html").read_bytes()
    assert page.html == page.raw.decode("utf-8")
    for text in load_expectations("static-table")["fetch_text_contains"]:
        assert text in page.html


def test_windows_1254_page_keeps_its_turkish_letters(site: LocalSite) -> None:
    url = serve_page(site, "windows-1254")  # sent as plain text/html: the charset is in the <meta>
    with make_client("tr") as client:
        page = fetch_page(client, url)
    assert page.status == 200
    assert page.encoding == "cp1254"
    for text in load_expectations("windows-1254")["fetch_text_contains"]:
        assert text in page.html
    assert page.raw == (PAGES_DIR / "windows-1254" / "page.html").read_bytes()


def test_page_over_size_cap_fails_as_too_large(site: LocalSite) -> None:
    site.add("/big", b"a" * (MAX_PAGE_BYTES + 1024 * 1024))
    with make_client("en") as client, pytest.raises(FetchFailure) as caught:
        fetch_page(client, site.url("/big"))
    assert caught.value.status is CaptureStatus.TOO_LARGE
    assert str(MAX_PAGE_BYTES) in caught.value.detail


def test_page_at_the_size_cap_is_kept_whole(site: LocalSite) -> None:
    site.add("/edge", b"b" * MAX_PAGE_BYTES)
    with make_client("en") as client:
        page = fetch_page(client, site.url("/edge"))
    assert len(page.raw) == MAX_PAGE_BYTES


def test_slow_page_fails_as_timeout(site: LocalSite) -> None:
    site.add("/slow", "<p>late</p>", delay_s=2)
    with make_client("en", timeout_s=0.5) as client, pytest.raises(FetchFailure) as caught:
        fetch_page(client, site.url("/slow"))
    assert caught.value.status is CaptureStatus.TIMEOUT
    assert caught.value.detail == "timed out (ReadTimeout) reaching 127.0.0.1"


@pytest.mark.parametrize(
    "error",
    [httpx2.ConnectTimeout, httpx2.ReadTimeout, httpx2.WriteTimeout, httpx2.PoolTimeout],
)
def test_a_timeout_names_its_kind_and_the_site(error: type[httpx2.TimeoutException]) -> None:
    def stall(request: httpx2.Request) -> httpx2.Response:
        raise error("timed out", request=request)

    transport = httpx2.MockTransport(stall)
    with httpx2.Client(transport=transport) as client, pytest.raises(FetchFailure) as caught:
        fetch_page(client, "http://shop.example:8443/pricing")
    assert caught.value.status is CaptureStatus.TIMEOUT
    assert caught.value.detail == f"timed out ({error.__name__}) reaching shop.example"


def test_a_timeout_after_a_redirect_names_the_site_that_stalled() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "old.example":
            return httpx2.Response(302, headers={"Location": "http://new.example/plans"})
        raise httpx2.ReadTimeout("timed out", request=request)

    transport = httpx2.MockTransport(handler)
    with httpx2.Client(transport=transport) as client, pytest.raises(FetchFailure) as caught:
        fetch_page(client, "http://old.example/plans")
    assert caught.value.detail == "timed out (ReadTimeout) reaching new.example"


def test_a_timeout_names_the_site_spelled_as_the_rest_of_the_capture_spells_it() -> None:
    def stall(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("timed out", request=request)

    transport = httpx2.MockTransport(stall)
    with httpx2.Client(transport=transport) as client, pytest.raises(FetchFailure) as caught:
        fetch_page(client, "http://user:pw@Bücher.example./preise")
    assert caught.value.detail == "timed out (ReadTimeout) reaching xn--bcher-kva.example"


def test_a_timeout_that_carries_no_request_names_the_site_asked_for() -> None:
    detail = _timeout_detail(httpx2.ReadTimeout("timed out"), "http://bücher.example/preise")
    assert detail == "timed out (ReadTimeout) reaching xn--bcher-kva.example"


def test_not_found_is_returned_not_raised(site: LocalSite) -> None:
    site.add("/gone", "<p>no such plan</p>", status=404)
    with make_client("en") as client:
        page = fetch_page(client, site.url("/gone"))
    assert page.status == 404
    assert "no such plan" in page.html


def test_bot_wall_status_is_returned_not_raised(site: LocalSite) -> None:
    url = serve_page(site, "bot-wall")
    with make_client("en") as client:
        assert fetch_page(client, url).status == 403


def test_redirects_are_followed_to_the_final_url(site: LocalSite) -> None:
    site.redirect("/old", "/new", status=301)
    site.add("/new", "<p>€5</p>")
    with make_client("en") as client:
        page = fetch_page(client, site.url("/old"))
    assert page.url == site.url("/old")
    assert page.final_url == site.url("/new")
    assert page.html == "<p>€5</p>"


def test_more_than_five_redirects_fail_as_http_error(site: LocalSite) -> None:
    for hop in range(MAX_REDIRECTS + 1):
        site.redirect(f"/hop{hop}", f"/hop{hop + 1}")
    site.add(f"/hop{MAX_REDIRECTS + 1}", "<p>end</p>")
    with make_client("en") as client, pytest.raises(FetchFailure) as caught:
        fetch_page(client, site.url("/hop0"))
    assert caught.value.status is CaptureStatus.HTTP_ERROR
    assert "redirects" in caught.value.detail


def test_five_redirects_are_followed(site: LocalSite) -> None:
    for hop in range(MAX_REDIRECTS):
        site.redirect(f"/hop{hop}", f"/hop{hop + 1}")
    site.add(f"/hop{MAX_REDIRECTS}", "<p>end</p>")
    with make_client("en") as client:
        assert fetch_page(client, site.url("/hop0")).html == "<p>end</p>"


def test_connection_error_fails_as_http_error() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    transport = httpx2.MockTransport(refuse)
    with httpx2.Client(transport=transport) as client, pytest.raises(FetchFailure) as caught:
        fetch_page(client, "http://pages.test/")
    assert caught.value.status is CaptureStatus.HTTP_ERROR
    assert caught.value.detail == "unreachable: connection refused"


def test_corrupt_gzip_body_fails_as_http_error(site: LocalSite) -> None:
    # Claims gzip but is not gzip: the failure comes while the body is read, not from the transport.
    site.add("/bad", b"<p>plain</p>", headers={"Content-Encoding": "gzip"})
    with make_client("en") as client, pytest.raises(FetchFailure) as caught:
        fetch_page(client, site.url("/bad"))
    assert caught.value.status is CaptureStatus.HTTP_ERROR
    assert caught.value.detail.startswith("unreadable")


@pytest.mark.parametrize("url", ["http://[::1", "http://127.0.0.1:abc/", "ftp://pages.test/", ""])
def test_url_that_cannot_be_requested_fails_as_http_error(url: str) -> None:
    with make_client("en") as client, pytest.raises(FetchFailure) as caught:
        fetch_page(client, url)
    assert caught.value.status is CaptureStatus.HTTP_ERROR


def test_host_name_that_cannot_be_encoded_fails_as_http_error() -> None:
    # What the socket layer raises for a host such as `a..b`, which httpx2 does not wrap.
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise UnicodeError("label empty or too long")

    transport = httpx2.MockTransport(refuse)
    with httpx2.Client(transport=transport) as client, pytest.raises(FetchFailure) as caught:
        fetch_page(client, "http://a..b/")
    assert caught.value.status is CaptureStatus.HTTP_ERROR


def test_only_the_kept_headers_are_kept(site: LocalSite) -> None:
    site.add(
        "/h",
        "<p>x</p>",
        headers={
            "Content-Language": "nl-NL",
            "CF-Mitigated": "challenge",
            "CF-Ray": "abc123-AMS",
            "Set-Cookie": "session=secret",
            "X-Other": "dropped",
        },
    )
    with make_client("en") as client:
        page = fetch_page(client, site.url("/h"))
    assert set(page.headers) <= set(KEPT_HEADERS)
    assert page.headers["content-type"] == "text/html; charset=utf-8"
    assert page.headers["content-language"] == "nl-NL"
    assert page.headers["cf-mitigated"] == "challenge"
    assert page.headers["cf-ray"] == "abc123-AMS"
    assert "server" in page.headers  # the local test server names itself
    assert "set-cookie" not in page.headers
    assert "x-other" not in page.headers


def test_a_kept_header_that_is_absent_is_left_out(site: LocalSite) -> None:
    site.add("/plain", "<p>x</p>")
    with make_client("en") as client:
        page = fetch_page(client, site.url("/plain"))
    assert "cf-ray" not in page.headers
    assert "content-language" not in page.headers


def test_the_client_sends_a_named_user_agent_and_the_language(site: LocalSite) -> None:
    with make_client("nl-NL,nl;q=0.9") as client:
        request = client.build_request("GET", site.url("/x"))
    assert request.headers["user-agent"].startswith(f"mihenk/{__version__} ")
    assert request.headers["accept-language"] == "nl-NL,nl;q=0.9"
    assert request.headers["accept"] == "text/html,application/xhtml+xml"


def test_the_client_leaves_redirects_to_open() -> None:
    # Every request goes through `_open`, which follows each hop itself (a redirect's body is
    # never read), so the client must not follow any on its own.
    with make_client("en", timeout_s=7) as client:
        assert isinstance(client, httpx2.Client)
        assert client.follow_redirects is False
        assert client.timeout.read == 7


def test_a_redirect_is_followed_by_fetch_page_and_not_by_the_client(site: LocalSite) -> None:
    site.redirect("/old", "/new")
    site.add("/new", "<p>€5</p>")
    with make_client("en") as client:
        assert client.get(site.url("/old")).status_code == 302
        assert fetch_page(client, site.url("/old")).final_url == site.url("/new")


def test_gzip_pages_are_decoded(site: LocalSite) -> None:
    html = "<p>Aylık €19</p>"
    site.add("/gz", gzip.compress(html.encode()), headers={"Content-Encoding": "gzip"})
    with make_client("en") as client:
        page = fetch_page(client, site.url("/gz"))
    assert page.html == html
    assert page.raw == html.encode()


def test_before_request_is_called_for_the_page_and_every_redirect_hop(site: LocalSite) -> None:
    site.redirect("/old", "/mid", status=301)
    site.redirect("/mid", "/new")
    site.add("/new", "<p>new</p>")
    seen: list[str] = []
    with make_client("en") as client:
        page = fetch_page(client, site.url("/old"), before_request=seen.append)
    assert seen == [site.url("/old"), site.url("/mid"), site.url("/new")]
    assert page.final_url == site.url("/new")


def test_before_request_can_stop_a_redirect_before_it_is_requested(site: LocalSite) -> None:
    site.redirect("/old", "/private")
    site.add("/private", "<p>secret</p>")

    def refuse_private(url: str) -> None:
        if url.endswith("/private"):
            raise FetchFailure(CaptureStatus.BLOCKED_BY_ROBOTS, "not for robots")

    with make_client("en") as client, pytest.raises(FetchFailure) as caught:
        fetch_page(client, site.url("/old"), before_request=refuse_private)
    assert caught.value.status is CaptureStatus.BLOCKED_BY_ROBOTS
    assert caught.value.detail == "not for robots"
    assert site.hits == ["/old"]
