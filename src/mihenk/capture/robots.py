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
    parts = urlsplit(page_url)
    return urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))


def decide(fetch: RobotsFetch, page_url: str) -> RobotsDecision:
    status = fetch.status
    if status is None:
        return RobotsDecision(False, f"robots.txt {fetch.detail}; treated as disallow-all")
    if 200 <= status < 300:
        text = (fetch.body or b"")[:MAX_ROBOTS_BYTES].decode("utf-8", errors="replace")
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
        url = robots_url(page_url)
        if url not in self._cache:
            self._cache[url] = self._fetch(url)
        return decide(self._cache[url], page_url)
