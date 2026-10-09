"""The trap pages under tests/fixtures/pages: small pages, each built to trip one known capture
problem, with an `expect.json` next to each. This module reads the expectations and serves a page
on a `LocalSite`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.helpers.site import LocalSite

PAGES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "pages"

# `Method` and `CaptureStatus` arrive with Task 1.4, which checks that its enums match these.
METHODS = frozenset({"fetch", "render", "render_interact"})
STATUSES = frozenset(
    {
        "ok",
        "blocked_by_robots",
        "http_error",
        "timeout",
        "needs_human",
        "too_large",
        "browser_unavailable",
        "action_failed",
    }
)

# How long `/poll` takes to answer on the never-idle page, so the network never goes idle.
POLL_DELAY_S = 5


def page_names() -> list[str]:
    """Every page folder, sorted."""
    return sorted(path.name for path in PAGES_DIR.iterdir() if path.is_dir())


def load_expectations(name: str) -> dict[str, Any]:
    text = (PAGES_DIR / name / "expect.json").read_text(encoding="utf-8")
    expectations: dict[str, Any] = json.loads(text)
    return expectations


def serve_page(site: LocalSite, name: str) -> str:
    """Register the page at `/<name>` and return its URL.

    `windows-1254` is sent as plain `text/html`, so the charset has to come from the page's own
    `<meta>`. `bot-wall` answers 403, and `never-idle` also gets the slow `/poll` route it calls.
    """
    path = f"/{name}"
    body = (PAGES_DIR / name / "page.html").read_bytes()
    if name == "windows-1254":
        site.add(path, body, content_type="text/html")
    elif name == "bot-wall":
        site.add(path, body, status=403)
    else:
        site.add(path, body)
    if name == "never-idle":
        site.add("/poll", b'{"ok": true}', content_type="application/json", delay_s=POLL_DELAY_S)
    return site.url(path)
