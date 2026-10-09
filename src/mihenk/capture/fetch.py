"""Plain HTTP capture (design §8.3) and the robots.txt fetch (§8.2)."""

from __future__ import annotations

import codecs
import re
from collections.abc import Mapping
from dataclasses import dataclass

import httpx2 as http

from mihenk import __version__
from mihenk.capture.models import CaptureStatus
from mihenk.capture.robots import MAX_REDIRECTS, MAX_ROBOTS_BYTES, RobotsFetch

MAX_PAGE_BYTES = 15 * 1024 * 1024
KEPT_HEADERS = ("content-type", "content-language", "server", "cf-mitigated", "cf-ray")
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


def _codec(name: str | None) -> str | None:
    if not name:
        return None
    try:
        return codecs.lookup(name).name
    except LookupError:
        return None


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


def _read_capped(response: http.Response, cap: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > cap:
            raise FetchFailure(CaptureStatus.TOO_LARGE, f"larger than {cap} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_page(client: http.Client, url: str) -> FetchedPage:
    try:
        with client.stream("GET", url) as response:
            raw = _read_capped(response, MAX_PAGE_BYTES)
            headers = {k: response.headers[k] for k in KEPT_HEADERS if k in response.headers}
            html, encoding = decode_html(raw, response.headers.get("content-type"))
            return FetchedPage(
                url, str(response.url), response.status_code, headers, raw, html, encoding
            )
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


def fetch_robots(client: http.Client, url: str) -> RobotsFetch:
    """Never raises: every failure is a `RobotsFetch` with no status, which `decide` disallows."""
    try:
        with client.stream("GET", url) as response:
            body = b""
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) >= MAX_ROBOTS_BYTES:
                    break  # RFC 9309 lets crawlers stop parsing after the limit
            return RobotsFetch(response.status_code, body[:MAX_ROBOTS_BYTES], "fetched")
    except http.TooManyRedirects:
        return RobotsFetch(None, None, f"unreachable: more than {MAX_REDIRECTS} redirects")
    except (http.HTTPError, http.InvalidURL, UnicodeError) as exc:
        # HTTPError covers timeouts, transport errors and a body that cannot be decoded;
        # UnicodeError is a host name that cannot be encoded (a..b), which httpx2 does not wrap.
        return RobotsFetch(None, None, f"unreachable: {type(exc).__name__}")
