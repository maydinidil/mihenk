"""Recognising bot walls, so they are recorded as needs_human (design §15)."""

from __future__ import annotations

import re

# Markers that only a challenge or block page carries, so they count at any status.
_ALWAYS = ("px-captcha", "captcha-delivery", "cf-chl-", "incapsula incident id")
# Cloudflare's JavaScript detections and Imperva's resource script are also injected into ordinary
# pages the site served without a challenge, so they count only when the site refused the request.
_WHEN_REFUSED = ("/cdn-cgi/challenge-platform", "_incapsula_resource")
_REFUSING_STATUSES = (403, 429, 503)
_TITLES = ("just a moment", "attention required", "access denied", "please verify you are a human")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def looks_like_bot_wall(status: int | None, html: str) -> bool:
    head = html[:200_000].lower()
    if any(marker in head for marker in _ALWAYS):
        return True
    if status not in _REFUSING_STATUSES:
        return False
    if any(marker in head for marker in _WHEN_REFUSED):
        return True
    match = _TITLE.search(head)
    title = match.group(1).strip() if match else ""
    return any(title.startswith(t) for t in _TITLES)
