"""At most one request per site every min_interval_s seconds (design §8.2).

Used only on the capture thread, so it needs no lock.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}


def host_key(url: str) -> str:
    """The site a URL belongs to, spelled one way, so no spelling gets its own pacing slot.

    Lower-case IDNA host without a trailing dot, plus the port only when it is not the scheme's
    default. Never the user name or password.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").rstrip(".")
    # A name that is not valid IDNA stays as written (already lower-cased by hostname).
    with contextlib.suppress(UnicodeError):
        host = host.encode("idna").decode("ascii")
    if ":" in host:
        host = f"[{host}]"
    port = parts.port
    if port is None or port == _DEFAULT_PORTS.get(parts.scheme.lower()):
        return host
    return f"{host}:{port}"


class Pace:
    def __init__(
        self,
        min_interval_s: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._min = min_interval_s
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}

    def wait(self, host: str) -> float:
        now = self._clock()
        last = self._last.get(host)
        delay = 0.0 if last is None else max(0.0, last + self._min - now)
        if delay > 0:
            self._sleep(delay)
        self._last[host] = now + delay
        return delay
