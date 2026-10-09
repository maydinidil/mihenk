"""At most one request per site every min_interval_s seconds (design §8.2).

Used only on the capture thread, so it needs no lock.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from urllib.parse import urlsplit


def host_key(url: str) -> str:
    return urlsplit(url).netloc.lower()


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
