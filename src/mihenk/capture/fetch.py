"""Plain HTTP capture (design §8.3) and the robots.txt fetch (§8.2)."""

from __future__ import annotations

import codecs
import contextlib
import re
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass

import httpx2 as http

from mihenk import __version__
from mihenk.capture.models import CaptureStatus
from mihenk.capture.pace import idna_host
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
_HEADER_CHARSET = re.compile(r"""charset\s*=\s*["']?([A-Za-z0-9_.:-]+)""", re.IGNORECASE)
# The WHATWG prescan reads the first 1024 bytes only and skips the comments in them. A comment
# that is never closed runs to the end of those bytes.
_META_WINDOW = 1024
_HTML_COMMENT = re.compile(rb"<!--.*?(?:-->|\Z)", re.DOTALL)
# A page with no declared charset whose bytes are not UTF-8 gets a second look: its <meta
# charset> may sit past the first 1024 bytes (after a long script or style block), which a
# browser would still find, as the prescan is only a first guess. The rest of the head is read,
# up to this many bytes.
_LATE_META_LIMIT = 64 * 1024
_HEAD_END = re.compile(rb"</head", re.IGNORECASE)


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
# The last four are the WHATWG labels whose Python codec is narrower than the browsers' (GB 2312
# is read as GBK, TIS-620 and ISO-8859-11 as windows-874) or reads a bare "utf-16" as the
# machine's byte order (WHATWG: little-endian).
_WHATWG_CODEC = {
    "iso8859-1": "cp1252",
    "ascii": "cp1252",
    "iso8859-9": "cp1254",
    "utf-16": "utf-16-le",
    "gb2312": "gbk",
    "tis-620": "cp874",
    "iso8859-11": "cp874",
}
# The encodings the WHATWG table lists, as Python names them. `codecs.lookup` also finds names
# that are not text encodings at all (hex, rot13, undefined) and text encodings no browser reads
# (utf-7, utf-32, unicode_escape, mbcs, cp437...). A page can declare any of them, so a charset
# outside this list is ignored, as if the page had not declared one.
_ALLOWED_CODECS = frozenset(
    codecs.lookup(name).name
    for name in (
        "utf-8",
        "utf-16-le",
        "utf-16-be",
        *(f"cp{number}" for number in range(1250, 1259)),
        *(f"iso8859-{number}" for number in (2, 3, 4, 5, 6, 7, 8, 10, 13, 14, 15, 16)),
        "koi8-r",
        "koi8-u",
        "cp866",
        "cp874",
        "mac-roman",
        "mac-cyrillic",
        "gbk",
        "gb18030",
        "big5",
        "big5hkscs",
        "euc-jp",
        "iso2022-jp",
        "shift_jis",
        "cp932",
        "euc-kr",
        "cp949",
    )
)
_UTF16_BOMS = (
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)


def _codec(name: str | None) -> str | None:
    if not name:
        return None
    try:
        normalised = codecs.lookup(name).name
    except LookupError:
        return None
    codec = _WHATWG_CODEC.get(normalised, normalised)
    return codec if codec in _ALLOWED_CODECS else None


def _declared_codec(window: bytes, cut: bool) -> str | None:
    """The usable charset a <meta> tag in `window` (comments already removed) declares. `cut` is
    whether the window ends before the page does."""
    meta = _META_CHARSET.search(window)
    if meta is not None and meta.end() == len(window) and cut:
        meta = None  # the window cut the value short (`big5` of `big5-hkscs`): not a declaration
    codec = _codec(meta.group(1).decode("ascii", "ignore") if meta else None)
    # The tag was read as ASCII-compatible bytes, so the page is not UTF-16 whatever it says.
    return "utf-8" if codec in ("utf-16-le", "utf-16-be") else codec


def _meta_codec(body: bytes) -> str | None:
    """The charset a <meta> tag in the first 1024 bytes declares, if it is a usable one."""
    window = _HTML_COMMENT.sub(b" ", body[:_META_WINDOW])
    return _declared_codec(window, len(body) > _META_WINDOW)


def _late_meta_codec(body: bytes) -> str | None:
    """The charset a <meta> tag declares anywhere in the head: up to `</head>` or the first
    64 KiB, comments skipped. For a page the first 1024 bytes did not settle."""
    region = _HTML_COMMENT.sub(b" ", body[:_LATE_META_LIMIT])
    head_end = _HEAD_END.search(region)
    if head_end is not None:
        return _declared_codec(region[: head_end.start()], cut=False)
    return _declared_codec(region, len(body) > _LATE_META_LIMIT)


def _is_utf8(body: bytes) -> bool:
    try:
        body.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def decode_html(body: bytes, content_type: str | None) -> tuple[str, str]:
    """Text and the encoding used: a BOM (UTF-8 or UTF-16), then the HTTP charset, then <meta
    charset> in the first 1024 bytes, then (for a body that is not valid UTF-8) a <meta charset>
    later in the head, then UTF-8. Only the encodings of the WHATWG table count; any other is
    ignored."""
    if body.startswith(codecs.BOM_UTF8):
        return body.decode("utf-8-sig", errors="replace"), "utf-8-sig"
    for bom, codec in _UTF16_BOMS:
        if body.startswith(bom):
            return body[len(bom) :].decode(codec, errors="replace"), codec
    header = _HEADER_CHARSET.search(content_type or "")
    declared = _codec(header.group(1) if header else None) or _meta_codec(body)
    if declared is None and not _is_utf8(body):
        declared = _late_meta_codec(body)
    encoding = declared or "utf-8"
    return body.decode(encoding, errors="replace"), encoding


def make_client(accept_language: str, timeout_s: float = 30.0) -> http.Client:
    return http.Client(
        headers={
            "User-Agent": f"mihenk/{__version__} (+https://github.com/maydinidil/mihenk)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": accept_language,
        },
        timeout=timeout_s,
        follow_redirects=False,  # `_open` follows every hop itself, so the client never does
    )


class _DeadlinePassed(Exception):
    """Internal: the fetch ran out of time. Each public function turns it into its own result."""


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise _DeadlinePassed


def _timeout_detail(exc: http.TimeoutException, url: str) -> str:
    """Which timeout, and for which site: the host of the request that stalled (a redirect hop
    can lead to another site than `url`), spelled as `idna_host` spells it."""
    with contextlib.suppress(RuntimeError):  # no request on the exception: name the asked-for site
        url = str(exc.request.url)
    return f"timed out ({type(exc).__name__}) reaching {idna_host(url)}"


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
        raise FetchFailure(CaptureStatus.TIMEOUT, _timeout_detail(exc, url)) from exc
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
                if len(body) > MAX_ROBOTS_BYTES:
                    # RFC 9309 lets crawlers stop parsing after the limit. One byte more is kept
                    # so that `decide` can tell a body that is longer than the limit from one
                    # that is exactly as long, and cut the longer one at its last line break.
                    break
                _check_deadline(deadline)
            return RobotsFetch(response.status_code, body[: MAX_ROBOTS_BYTES + 1], "fetched")
    except _DeadlinePassed:
        return RobotsFetch(None, None, "unreachable: deadline passed")
    except http.TooManyRedirects:
        return RobotsFetch(None, None, f"unreachable: more than {MAX_REDIRECTS} redirects")
    except http.TimeoutException as exc:
        return RobotsFetch(None, None, f"unreachable: {_timeout_detail(exc, url)}")
    except (http.HTTPError, http.InvalidURL, UnicodeError) as exc:
        # HTTPError covers transport errors and a body that cannot be decoded (timeouts are
        # answered above, with their kind and site); UnicodeError is a host name that cannot be encoded (a..b), which httpx2 does not wrap.
        return RobotsFetch(None, None, f"unreachable: {type(exc).__name__}")
