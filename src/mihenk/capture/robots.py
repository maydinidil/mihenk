"""robots.txt decisions (design §8.2): RFC 9309 matching through protego.

mihenk is stricter than RFC 9309 in three places, as a politeness choice: 401 and 403 are
treated as disallow-all (the RFC allows everything on any 4xx), 429 disallows for the run,
and more than five redirects counts as unreachable. Every decision carries its reason.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from protego import Protego

from mihenk.capture.pace import host_key

USER_AGENT_TOKEN = "mihenk"  # noqa: S105 - a robots.txt product token, not a secret
MAX_ROBOTS_BYTES = 512 * 1024
MAX_REDIRECTS = 5


@dataclass(frozen=True)
class RobotsFetch:
    status: int | None
    body: bytes | None
    detail: str


@dataclass(frozen=True)
class RobotsDecision:
    allowed: bool
    reason: str


def robots_url(page_url: str) -> str:
    """The robots.txt of a page's site, with the site spelled one way (as `host_key` does).

    The scheme in lower case, the host in IDNA without a trailing dot or the scheme's default
    port, IPv6 in brackets, and no user name or password. The gate caches by this address, so
    `HTTP://Shop.example:80/x` and `http://shop.example/x` cost one fetch, and a password in a
    typed address is never sent on to robots.txt.
    """
    scheme = urlsplit(page_url).scheme.lower()
    return urlunsplit((scheme, host_key(page_url), "/robots.txt", "", ""))


def _within_limit(body: bytes) -> bytes:
    """The body as it is read: whole when it fits `MAX_ROBOTS_BYTES`, else cut back to the last
    line break inside the limit, so the last rule is never read half-written (`Disallow: /p`
    cut from `Disallow: /private` would block `/public`). A bare CR ends a line too (RFC 9309).
    `fetch_robots` hands over one byte more than the limit, so a longer body shows as longer.
    """
    if len(body) <= MAX_ROBOTS_BYTES:
        return body
    kept = body[:MAX_ROBOTS_BYTES]
    return kept[: max(kept.rfind(b"\n"), kept.rfind(b"\r")) + 1]


def decide(fetch: RobotsFetch, page_url: str) -> RobotsDecision:
    status = fetch.status
    if status is None:
        return RobotsDecision(False, f"robots.txt {fetch.detail}; treated as disallow-all")
    if 200 <= status < 300:
        if fetch.body is None:
            return RobotsDecision(False, "robots.txt body unreadable; treated as disallow-all")
        # utf-8-sig: a byte order mark would otherwise hide the first group's user-agent line.
        text = _within_limit(fetch.body).decode("utf-8-sig", errors="replace")
        if Protego.parse(text).can_fetch(page_url, USER_AGENT_TOKEN):
            return RobotsDecision(True, "allowed by the robots.txt rules")
        return RobotsDecision(False, "disallowed by the robots.txt rules")
    if status in (401, 403):
        return RobotsDecision(
            False, f"robots.txt answered {status}; mihenk treats this as disallow-all"
        )
    if status == 429:
        return RobotsDecision(False, "robots.txt answered 429 (slow down); disallowed for this run")
    if 400 <= status < 500:
        return RobotsDecision(True, f"no robots.txt (answered {status}); allowed")
    return RobotsDecision(False, f"robots.txt answered {status}; treated as disallow-all")


class RobotsGate:
    """One robots.txt fetch per site per run."""

    def __init__(self, fetch_robots: Callable[[str], RobotsFetch]) -> None:
        self._fetch = fetch_robots
        self._cache: dict[str, RobotsFetch] = {}

    def check(self, page_url: str) -> RobotsDecision:
        try:
            url = robots_url(page_url)
        except ValueError:  # a port out of range (:99999), an unclosed IPv6 bracket
            return RobotsDecision(False, "not a valid http(s) URL; treated as disallow-all")
        if url not in self._cache:
            self._cache[url] = self._fetch(url)
        return decide(self._cache[url], page_url)
