"""The trap pages: each is a small page built to trip one known capture problem (design §16).

These tests check the fixtures themselves (that every page is complete, stays on its own host and
really contains its trap) and the helper that serves them. Capturing them is Task 1.9's job.
"""

from __future__ import annotations

import html
import json
import re
import socket
import struct
import time
from typing import Any

import httpx
import pytest

from tests.helpers.pages import (
    ACTION_KINDS,
    METHODS,
    PAGES_DIR,
    STATUSES,
    STRUCTURED_KINDS,
    load_expectations,
    page_names,
    serve_page,
)
from tests.helpers.site import LocalSite

TRAP_PAGES = frozenset(
    {
        "static-table",
        "js-only-prices",
        "billing-toggle",
        "jsonld-currency-mismatch",
        "next-data",
        "split-digits",
        "svg-noise",
        "never-idle",
        "windows-1254",
        "huge-blob",
        "bot-wall",
        "vat-en",
        "vat-nl",
        "vat-de",
        "vat-fr",
        "vat-es",
        "vat-it",
        "vat-tr",
    }
)
VAT_PAGES = sorted(name for name in TRAP_PAGES if name.startswith("vat-"))

# The shape documented in Task 1.1. The kinds mirror `StructuredKind` (Task 1.5), `VatPhrase`
# (Task 1.6) and the recipe actions (Task 1.8).
EXPECT_KEYS = {
    "methods",
    "status",
    "fetch_text_contains",
    "fetch_text_lacks",
    "render_text_contains",
    "states",
    "structured",
    "locale",
}
STATE_KEYS = {"label", "actions", "text_contains", "text_lacks"}
LOCALE_KEYS = {"html_lang", "content_language", "currency_symbols", "currency_codes", "vat_phrases"}

URL = re.compile(rb"(?:https?|wss?)://[^\s\"'<>()\\]*", re.IGNORECASE)
# A reference that takes the scheme of the page and so names another host: in an attribute, in
# CSS (`url(//host)`, `@import "//host"`, and `@import url(//host)`, which is the first again), and
# in a meta refresh (`content="0; url=//host"`).
PROTOCOL_RELATIVE = re.compile(
    rb"""(?:(?:src|href|action|poster|srcset)\s*=\s*["']?\s*//)"""
    rb"""|(?:\burl\s*\(\s*["']?\s*//)"""
    rb"""|(?:@import\s*["']\s*//)"""
    rb"""|(?:\burl\s*=\s*["']?\s*//)""",
    re.IGNORECASE,
)


def _page_bytes(name: str) -> bytes:
    return (PAGES_DIR / name / "page.html").read_bytes()


def _page_text(name: str) -> str:
    """The page as text; only `windows-1254` is not UTF-8."""
    encoding = "cp1254" if name == "windows-1254" else "utf-8"
    return _page_bytes(name).decode(encoding)


def _allowed_url(url: str) -> bool:
    """Namespace identifiers that browsers never fetch."""
    if url == "http://www.w3.org/2000/svg":
        return True
    return url == "https://schema.org" or url.startswith("https://schema.org/")


def test_the_planned_trap_pages_exist() -> None:
    assert set(page_names()) >= TRAP_PAGES


@pytest.mark.parametrize("name", page_names())
def test_every_page_folder_has_both_files(name: str) -> None:
    assert (PAGES_DIR / name / "page.html").is_file()
    assert (PAGES_DIR / name / "expect.json").is_file()


# Every page captures as `ok` except the ones named here.
NOT_OK = {"bot-wall": "needs_human"}


@pytest.mark.parametrize("name", page_names())
def test_expectations_have_methods_and_status(name: str) -> None:
    expect = load_expectations(name)
    assert isinstance(expect["methods"], list)
    assert expect["methods"], "a page is captured by at least one method"
    assert set(expect["methods"]) <= METHODS
    assert expect["status"] in STATUSES
    # Not only a valid status but the right one: a page that quietly expected `http_error` would
    # let the capture tests pass over a failure.
    assert expect["status"] == NOT_OK.get(name, "ok")


def test_the_pages_that_are_not_ok_are_real_pages() -> None:
    assert set(NOT_OK) <= set(page_names())


# These pages cannot be checked against their source: split-digits writes a price across spans, so
# its text is only there once the page is read as text, and js-only-prices builds its prices in
# script.
NOT_IN_SOURCE = {"js-only-prices", "split-digits"}


@pytest.mark.parametrize("name", [n for n in page_names() if n not in NOT_IN_SOURCE])
def test_the_text_a_fetch_must_find_is_in_the_page_source(name: str) -> None:
    source = html.unescape(_page_text(name))
    for wanted in load_expectations(name).get("fetch_text_contains", []):
        assert wanted in source, f"{name}: {wanted!r} is not in the page source"


def test_the_pages_checked_against_their_source_are_not_none() -> None:
    checked = [n for n in page_names() if n not in NOT_IN_SOURCE]
    assert len(checked) >= 15
    assert set(page_names()) >= NOT_IN_SOURCE


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item for item in value)


@pytest.mark.parametrize("name", page_names())
def test_expectations_follow_the_documented_shape(name: str) -> None:
    expect = load_expectations(name)
    assert set(expect) <= EXPECT_KEYS
    for key in ("fetch_text_contains", "fetch_text_lacks", "render_text_contains"):
        assert _string_list(expect.get(key, []))
    # A page with states is captured by render_interact, and only those pages are.
    assert ("states" in expect) == ("render_interact" in expect["methods"])
    for state in expect.get("states", []):
        assert set(state) == STATE_KEYS
        assert isinstance(state["label"], str) and state["label"]
        assert all(action["kind"] in ACTION_KINDS for action in state["actions"])
        assert _string_list(state["text_contains"])
        assert _string_list(state["text_lacks"])
    for block in expect.get("structured", []):
        assert set(block) == {"kind", "problem"}
        assert block["kind"] in STRUCTURED_KINDS
        assert block["problem"] is None or isinstance(block["problem"], str)
    locale = expect.get("locale", {})
    assert set(locale) <= LOCALE_KEYS
    for phrase in locale.get("vat_phrases", []):
        assert set(phrase) == {"language", "kind", "phrase"}
        assert phrase["kind"] in {"incl", "excl"}


def _other_host_references(data: bytes) -> list[str]:
    """Every address in the page that is not one of the namespace names a browser never fetches:
    absolute http, https, ws and wss URLs, and the references that borrow the page's scheme."""
    urls = [match.group(0).decode("latin-1") for match in URL.finditer(data)]
    found = [url for url in urls if not _allowed_url(url)]
    found += [match.group(0).decode("latin-1") for match in PROTOCOL_RELATIVE.finditer(data)]
    return found


@pytest.mark.parametrize("name", page_names())
def test_no_page_references_another_host(name: str) -> None:
    foreign = _other_host_references(_page_bytes(name))
    assert not foreign, f"{name} references {foreign[:3]}"


@pytest.mark.parametrize(
    "sample",
    [
        '<a href="https://cdn.example/x">x</a>',
        '<img src="http://cdn.example/x.png">',
        '<a href="//cdn.example/x">x</a>',
        "<img src=//cdn.example/x.png>",
        "<img srcset='//cdn.example/x.png 2x'>",
        '<form action = "//cdn.example/post">',
        '<video poster="//cdn.example/p.jpg"></video>',
        '<div style="background: url(//cdn.example/x.png)"></div>',
        "<div style=\"background: url( '//cdn.example/x.png' )\"></div>",
        '<style>div { background: URL("//cdn.example/x.png") }</style>',
        '<style>@import "//cdn.example/a.css";</style>',
        "<style>@import '//cdn.example/a.css';</style>",
        "<style>@import url(//cdn.example/a.css);</style>",
        "<style>@import url('//cdn.example/a.css');</style>",
        '<script>new WebSocket("ws://cdn.example/socket")</script>',
        '<script>new WebSocket("wss://cdn.example/socket")</script>',
        '<script>var s = "WSS://cdn.example/socket";</script>',
        '<meta http-equiv="refresh" content="0; url=//cdn.example/">',
        '<meta http-equiv="refresh" content="0;URL=//cdn.example/">',
        "<meta http-equiv='refresh' content='5; url = //cdn.example/'>",
        '<meta http-equiv="refresh" content="0; url=https://cdn.example/">',
    ],
)
def test_the_other_host_guard_catches_every_form(sample: str) -> None:
    assert _other_host_references(sample.encode()), sample


@pytest.mark.parametrize(
    "sample",
    [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8"></svg>',
        '<script type="application/ld+json">{"@context": "https://schema.org", "@type": "Offer"}</script>',
        '<script type="application/ld+json">{"@type": "https://schema.org/Offer"}</script>',
        '<a href="/pricing">Pricing</a><img src="logo.png"><a href="/a//b">x</a>',
        '<div style="background: url(/img/x.png)"></div>',
        '<div style="background: url(data:image/png;base64,iVBORw0KGgo=)"></div>',
        "<style>@import 'local.css'; @import url(local.css); a { color: red } /* // note */</style>",
        '<script>// a comment\nvar x = "a//b"; fetch("/poll");</script>',
        '<meta http-equiv="refresh" content="0; url=/other">',
        "<p>Two slashes // in text, and a url = in prose.</p>",
    ],
)
def test_the_other_host_guard_lets_local_references_through(sample: str) -> None:
    assert _other_host_references(sample.encode()) == []


# The traps themselves: a page that quietly lost its trap would let the capture tests pass
# without proving anything.


def test_windows_1254_page_is_really_in_that_encoding() -> None:
    data = _page_bytes("windows-1254")
    with pytest.raises(UnicodeDecodeError):
        data.decode("utf-8")
    assert b'<meta charset="windows-1254">' in data
    assert b"\r" not in data
    text = data.decode("cp1254")
    for expected in ("Aylık 199 TL", "Fiyatlara KDV dahildir", "İ", "ş", "ğ"):
        assert expected in text


def test_huge_blob_holds_a_json_block_of_about_3_mb() -> None:
    data = _page_bytes("huge-blob")
    blocks = re.findall(
        rb'<script type="application/json"[^>]*>(.*?)</script>', data, flags=re.DOTALL
    )
    assert len(blocks) == 1
    assert 3_000_000 <= len(blocks[0]) <= 3_100_000
    assert json.loads(blocks[0])


def test_bot_wall_looks_like_a_challenge_page() -> None:
    text = _page_text("bot-wall")
    assert "<title>Just a moment...</title>" in text
    assert re.search(r'<script[^>]+src="/cdn-cgi/challenge-platform/', text)


def test_split_digits_page_splits_the_price_across_spans() -> None:
    assert "<span>€</span><span>4</span><span>9</span>" in _page_text("split-digits")


def test_svg_noise_has_405_in_path_data_and_once_as_a_price() -> None:
    text = _page_text("svg-noise")
    assert re.search(r'<path[^>]+\bd="[^"]*405', text)
    assert text.count("405 Kč") == 1


def test_never_idle_page_polls_every_300_ms() -> None:
    text = _page_text("never-idle")
    assert "/poll" in text
    assert re.search(r"setInterval\([^;]*,\s*300\s*\)", text, flags=re.DOTALL)


def test_billing_toggle_starts_on_annual_with_a_monthly_button() -> None:
    text = _page_text("billing-toggle")
    assert "€24 / month, billed yearly" in text
    assert re.search(r"<button[^>]*>Monthly</button>", text)


def test_js_only_prices_are_absent_from_the_page_source() -> None:
    text = _page_text("js-only-prices")
    prices = [
        item for item in load_expectations("js-only-prices")["render_text_contains"] if "€" in item
    ]
    assert prices
    assert not [price for price in prices if price in text]


def test_jsonld_currency_differs_from_the_visible_currency() -> None:
    text = _page_text("jsonld-currency-mismatch")
    assert '<script type="application/ld+json">' in text
    assert '"priceCurrency": "USD"' in text
    assert "€" in text


def test_next_data_blob_is_present() -> None:
    assert '<script id="__NEXT_DATA__" type="application/json">' in _page_text("next-data")


@pytest.mark.parametrize("name", VAT_PAGES)
def test_vat_page_says_its_wording_in_its_language(name: str) -> None:
    locale = load_expectations(name)["locale"]
    language = name.removeprefix("vat-")
    text = _page_text(name)
    assert f'<html lang="{language}">' in text
    assert locale["html_lang"] == language
    assert locale["vat_phrases"]
    for phrase in locale["vat_phrases"]:
        assert phrase["language"] == language
        assert phrase["phrase"] in text


# Serving.


def test_serve_page_serves_every_file_at_its_name(site: LocalSite) -> None:
    # One site for all pages: each stopped site costs half a second.
    with httpx.Client(trust_env=False) as client:
        for name in page_names():
            url = serve_page(site, name)
            assert url == site.url(f"/{name}")
            response = client.get(url)
            assert response.status_code == (403 if name == "bot-wall" else 200), name
            assert response.content == _page_bytes(name), name
            expected_type = "text/html" if name == "windows-1254" else "text/html; charset=utf-8"
            assert response.headers["content-type"] == expected_type, name


def test_never_idle_page_also_gets_a_slow_poll_route(site: LocalSite) -> None:
    serve_page(site, "never-idle")
    assert site.routes["/poll"].delay_s == 5


def test_other_pages_get_no_poll_route(site: LocalSite) -> None:
    serve_page(site, "static-table")
    assert "/poll" not in site.routes


def test_a_client_that_leaves_during_a_delay_leaves_no_traceback(
    site: LocalSite, capfd: pytest.CaptureFixture[str]
) -> None:
    # The never-idle page's /poll answers after five seconds, and the browser closes the page
    # first. The server must not print a traceback for the connection nobody is waiting on.
    site.add("/slow", "<p>x</p>", delay_s=0.4)
    port = int(site.base_url.rsplit(":", 1)[1])
    with socket.create_connection(("127.0.0.1", port)) as connection:
        connection.sendall(b"GET /slow HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        deadline = time.monotonic() + 5
        while "/slow" not in site.hits:  # the server has read the request and is now delaying
            assert time.monotonic() < deadline
            time.sleep(0.01)
        # Closing with a zero linger time resets the connection, so the server's write fails.
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    time.sleep(1.0)
    assert capfd.readouterr().err == ""
