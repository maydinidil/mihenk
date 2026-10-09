"""Plain HTTP capture (design §8.3) and the robots.txt fetch (§8.2)."""

from __future__ import annotations

import codecs
import re
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass

import httpx2 as http

from mihenk import __version__
from mihenk.capture.models import CaptureStatus
from mihenk.capture.robots import MAX_REDIRECTS, MAX_ROBOTS_BYTES, RobotsFetch

MAX_PAGE_BYTES = 15 * 1024 * 1024
KEPT_HEADERS = ("content-type", "content-language", "server", "cf-mitigated", "cf-ray")
# The longest one fetch may take from its first request to its last byte. httpx2's own timeouts
# apply to each connect, read and write, so a server that trickles bytes would never trip them.
PAGE_DEADLINE_S = 90.0
ROBOTS_DEADLINE_S = 30.0
_META_CHARSET = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""", re.IGNORECASE
)
_HEADER_CHARSET = re.compile(r"charset\s*=\s*\"?([A-Za-z0-9_.:-]+)", re.IGNORECASE)


class FetchFailure(Exception):
    def __init__(self, status: CaptureStatus, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class FetchedPage:
    url: str
    final_url: str
    status: int
    headers: Mapping[str, str]
    raw: bytes
    html: str
    encoding: str


# Browsers read these labels as the Windows code page that extends them (WHATWG Encoding
# Standard), and real pages rely on it: a page labelled iso-8859-1 or us-ascii holds curly quotes
# and the euro sign. Python's codec table would turn those bytes into control characters or
# U+FFFD. Keys are the names `codecs.lookup` normalises the labels to (latin1, l1, us-ascii...).
_WHATWG_CODEC = {"iso8859-1": "cp1252", "ascii": "cp1252", "iso8859-9": "cp1254"}


def _codec(name: str | None) -> str | None:
    if not name:
        return None
    try:
        normalised = codecs.lookup(name).name
    except LookupError:
        return None
    return _WHATWG_CODEC.get(normalised, normalised)


def decode_html(body: bytes, content_type: str | None) -> tuple[str, str]:
    """Text and the encoding used: a BOM, then the HTTP charset, then <meta charset>, then UTF-8."""
    if body.startswith(codecs.BOM_UTF8):
        return body.decode("utf-8-sig", errors="replace"), "utf-8-sig"
    header = _HEADER_CHARSET.search(content_type or "")
    meta = _META_CHARSET.search(body[:4096])
    for candidate in (
        _codec(header.group(1) if header else None),
        _codec(meta.group(1).decode("ascii", "ignore") if meta else None),
        "utf-8",
    ):
        if candidate is None:
            continue
        try:
            return body.decode(candidate, errors="replace"), candidate
        except (LookupError, UnicodeError):
            # `codecs.lookup` also finds names that are not text encodings (hex, rot13,
            # undefined); a page can declare one, so fall through to the next candidate.
            continue
    raise AssertionError("utf-8 always exists")


def make_client(accept_language: str, timeout_s: float = 30.0) -> http.Client:
    return http.Client(
        headers={
            "User-Agent": f"mihenk/{__version__} (+https://github.com/maydinidil/mihenk)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": accept_language,
        },
        timeout=timeout_s,
        follow_redirects=True,
        max_redirects=MAX_REDIRECTS,
    )


class _DeadlinePassed(Exception):
    """Internal: the fetch ran out of time. Each public function turns it into its own result."""


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise _DeadlinePassed


@contextmanager
def _open(
    client: http.Client,
    url: str,
    deadline: float,
    before_request: Callable[[str], None] | None = None,
) -> Iterator[http.Response]:
    """The final response of a GET, its body still unread.

    Redirects are followed here, not by httpx2, which reads a redirect's body in full before it
    follows: an endless or huge 3xx body would sit outside the size caps and the deadline. A
    redirect's response is closed unread. At most MAX_REDIRECTS are followed; the next one raises
    `TooManyRedirects`. The deadline is checked before every request.

    `before_request` is called with the URL of every request, the first one and each redirect
    hop, after the previous response was closed and before the next one is sent. It may raise
    `FetchFailure` to stop (pacing and robots.txt checks for the site a redirect leads to).
    """
    request = client.build_request("GET", url)
    redirects = 0
    while True:
        if before_request is not None:
            before_request(str(request.url))
        _check_deadline(deadline)
        response = client.send(request, stream=True, follow_redirects=False)
        following = response.next_request
        if following is None:
            break
        response.close()
        if redirects >= MAX_REDIRECTS:
            raise http.TooManyRedirects("Exceeded maximum allowed redirects.", request=request)
        redirects += 1
        request = following
    try:
        yield response
    finally:
        response.close()


def _read_capped(response: http.Response, cap: int, deadline: float) -> bytes:
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > cap:
            raise FetchFailure(CaptureStatus.TOO_LARGE, f"larger than {cap} bytes")
        chunks.append(chunk)
        _check_deadline(deadline)
    return b"".join(chunks)


def fetch_page(
    client: http.Client,
    url: str,
    *,
    deadline_s: float = PAGE_DEADLINE_S,
    before_request: Callable[[str], None] | None = None,
) -> FetchedPage:
    deadline = time.monotonic() + deadline_s
    try:
        with _open(client, url, deadline, before_request) as response:
            raw = _read_capped(response, MAX_PAGE_BYTES, deadline)
            headers = {k: response.headers[k] for k in KEPT_HEADERS if k in response.headers}
            html, encoding = decode_html(raw, response.headers.get("content-type"))
            return FetchedPage(
                url, str(response.url), response.status_code, headers, raw, html, encoding
            )
    except _DeadlinePassed:
        raise FetchFailure(CaptureStatus.TIMEOUT, f"deadline of {deadline_s:g} s passed") from None
    except http.TimeoutException as exc:
        raise FetchFailure(CaptureStatus.TIMEOUT, f"timed out: {exc}") from exc
    except http.TooManyRedirects as exc:
        raise FetchFailure(
            CaptureStatus.HTTP_ERROR, f"more than {MAX_REDIRECTS} redirects"
        ) from exc
    except http.TransportError as exc:
        raise FetchFailure(CaptureStatus.HTTP_ERROR, f"unreachable: {exc}") from exc
    except (http.DecodingError, http.InvalidURL, UnicodeError) as exc:
        raise FetchFailure(CaptureStatus.HTTP_ERROR, f"unreadable: {exc}") from exc


def fetch_robots(
    client: http.Client,
    url: str,
    *,
    deadline_s: float = ROBOTS_DEADLINE_S,
    before_request: Callable[[str], None] | None = None,
) -> RobotsFetch:
    """Never raises: every failure is a `RobotsFetch` with no status, which `decide` disallows.

    `before_request` is called with the URL of every request, robots.txt itself and each redirect
    hop, as for `fetch_page`. It is for pacing, so it must not raise.
    """
    deadline = time.monotonic() + deadline_s
    try:
        with _open(client, url, deadline, before_request) as response:
            body = b""
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) >= MAX_ROBOTS_BYTES:
                    break  # RFC 9309 lets crawlers stop parsing after the limit
                _check_deadline(deadline)
            return RobotsFetch(response.status_code, body[:MAX_ROBOTS_BYTES], "fetched")
    except _DeadlinePassed:
        return RobotsFetch(None, None, "unreachable: deadline passed")
    except http.TooManyRedirects:
        return RobotsFetch(None, None, f"unreachable: more than {MAX_REDIRECTS} redirects")
    except (http.HTTPError, http.InvalidURL, UnicodeError) as exc:
        # HTTPError covers timeouts, transport errors and a body that cannot be decoded;
        # UnicodeError is a host name that cannot be encoded (a..b), which httpx2 does not wrap.
        return RobotsFetch(None, None, f"unreachable: {type(exc).__name__}")
