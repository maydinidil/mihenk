"""Capturing one page end to end (design §8.2, §8.3, §15). Runs on the capture thread only."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Browser
from playwright.sync_api import Error as PlaywrightError

from mihenk.capture.fetch import MAX_PAGE_BYTES, FetchFailure, fetch_page
from mihenk.capture.locale import detect_locale_markers
from mihenk.capture.models import CaptureStatus, Method
from mihenk.capture.pace import Pace, host_key
from mihenk.capture.recipe import Recipe
from mihenk.capture.render import RenderedState, RenderSettings, render_states
from mihenk.capture.robots import RobotsGate
from mihenk.capture.snapshot import SnapshotInput, SnapshotRef, write_snapshot
from mihenk.capture.walls import looks_like_bot_wall
from mihenk.trim.structured import extract_structured
from mihenk.trim.text import html_to_text


@dataclass(frozen=True)
class PageSpec:
    key: str
    url: str
    recipe: Recipe
    respect_robots: bool = True


@dataclass(frozen=True)
class CaptureResult:
    page_key: str
    state_label: str
    method: Method
    status: CaptureStatus
    detail: str
    snapshot: SnapshotRef | None


@dataclass
class RunContext:
    """Everything one run shares. The robots gate and the pace are shared by every page of the
    run; the http client is not: open one per brand and close it after, never share one across
    brands or runs, because its cookie jar would carry the first site's cookies to the next
    (design §8.3).

    The robots gate must fetch robots.txt with its own http client, never this one: a cookie
    that robots.txt sets must not reach the pages (design §8.3).
    """

    run_id: str
    snapshots_root: Path
    collection_country: str
    robots: RobotsGate
    pace: Pace
    http_client: Any  # the Client from fetch.make_client
    browser: Browser | None
    render: RenderSettings
    now: Callable[[], datetime]  # must return a UTC time


def _status_for(http_status: int | None, html: str) -> tuple[CaptureStatus, str]:
    if looks_like_bot_wall(http_status, html):
        return CaptureStatus.NEEDS_HUMAN, "the page is a bot check; a person has to open it"
    if http_status is not None and http_status >= 400:
        return CaptureStatus.HTTP_ERROR, f"answered {http_status}"
    if http_status is not None and http_status >= 300:
        # A redirect that was followed never gets here; a 3xx that is the final answer had no
        # Location to follow, so it holds no page.
        return CaptureStatus.HTTP_ERROR, f"answered {http_status} without a usable Location"
    return CaptureStatus.OK, "captured"


def is_http_url(url: str) -> bool:
    """An http or https URL with a host and a usable port."""
    try:
        parts = urlsplit(url)
        port = parts.port  # raises ValueError for a port that is not a number or out of range
    except ValueError:
        return False
    return parts.scheme.lower() in ("http", "https") and bool(parts.hostname) and port != 0


NO_BROWSER_DETAIL = (
    "no Chrome, Edge or downloaded Chromium was found; "
    'run "mihenk install-browser" to download Chromium'
)


def _for_every_state(spec: PageSpec, status: CaptureStatus, detail: str) -> list[CaptureResult]:
    return [
        CaptureResult(spec.key, state.label, spec.recipe.method, status, detail, None)
        for state in spec.recipe.states
    ]


def _robots_block(spec: PageSpec, ctx: RunContext) -> list[CaptureResult] | None:
    """The result for every state when robots.txt disallows the page, or None when it may go on."""
    if not spec.respect_robots:
        return None
    decision = ctx.robots.check(spec.url)
    if decision.allowed:
        return None
    return _for_every_state(spec, CaptureStatus.BLOCKED_BY_ROBOTS, decision.reason)


def capture_page(spec: PageSpec, ctx: RunContext) -> list[CaptureResult]:
    if not is_http_url(spec.url):
        return _for_every_state(
            spec, CaptureStatus.HTTP_ERROR, f"not a valid http(s) URL: {spec.url[:200]!r}"
        )
    if spec.recipe.method is Method.FETCH:
        blocked = _robots_block(spec, ctx)
        return blocked if blocked is not None else [_capture_fetch(spec, ctx)]
    browser = ctx.browser
    if browser is None:
        # Before the robots check: with no browser there is nothing to render, so no request
        # (not even robots.txt) is sent.
        return _for_every_state(spec, CaptureStatus.BROWSER_UNAVAILABLE, NO_BROWSER_DETAIL)
    blocked = _robots_block(spec, ctx)
    return blocked if blocked is not None else _capture_render(spec, ctx, browser)


def _capture_fetch(spec: PageSpec, ctx: RunContext) -> CaptureResult:
    label = spec.recipe.states[0].label
    requests = 0

    def before_request(url: str) -> None:
        # Called for the page and for every redirect hop. A redirect can lead to another site,
        # so each request is checked against the robots.txt of the site it goes to (design
        # §8.2), and paced against that site. The robots check comes first: it requests
        # robots.txt (paced by the gate's own fetch function), and the page request that follows
        # must be paced after it.
        nonlocal requests
        first = requests == 0
        requests += 1
        if spec.respect_robots:
            decision = ctx.robots.check(url)
            if not decision.allowed:
                reason = (
                    decision.reason
                    if first
                    else f"redirected to {host_key(url)}: " + decision.reason
                )
                raise FetchFailure(CaptureStatus.BLOCKED_BY_ROBOTS, reason)
        ctx.pace.wait(host_key(url))

    try:
        page = fetch_page(ctx.http_client, spec.url, before_request=before_request)
    except FetchFailure as exc:
        return CaptureResult(spec.key, label, Method.FETCH, exc.status, exc.detail, None)
    text = html_to_text(page.html)
    ref = write_snapshot(
        ctx.snapshots_root,
        SnapshotInput(
            run_id=ctx.run_id,
            page_key=spec.key,
            state_label=label,
            url=spec.url,
            final_url=page.final_url,
            http_status=page.status,
            method=Method.FETCH,
            captured_at=ctx.now(),
            html=page.html,
            raw_bytes=page.raw,
            encoding=page.encoding,
            text=text,
            structured=extract_structured(page.html),
            screenshot_png=None,
            locale=detect_locale_markers(page.html, text, page.headers),
            collection_country=ctx.collection_country,
        ),
    )
    status, detail = _status_for(page.status, page.html)
    return CaptureResult(spec.key, label, Method.FETCH, status, detail, ref)


def _first_line(exc: BaseException) -> str:
    for line in str(exc).splitlines():
        if line.strip():
            return line.strip()[:300]
    return type(exc).__name__


def _redirect_block(spec: PageSpec, ctx: RunContext, final_url: str) -> str | None:
    """Why the page a render ended on may not be kept, or None.

    Chrome follows redirects itself, so the site it ended on (or a path the first site's
    robots.txt allowed but the final one does not) is checked after the state rendered.
    """
    if not spec.respect_robots or not is_http_url(final_url):
        return None
    final_host = host_key(final_url)
    if final_host != host_key(spec.url):
        # Chrome has just requested the page from this other site, and the pace never saw it:
        # mark it, so that the robots.txt request that may follow waits its turn.
        ctx.pace.mark(final_host)
    decision = ctx.robots.check(final_url)
    if decision.allowed:
        return None
    return f"the page was reached by a redirect to {host_key(final_url)}: {decision.reason}"


def _capture_render(spec: PageSpec, ctx: RunContext, browser: Browser) -> list[CaptureResult]:
    method = spec.recipe.method
    host = host_key(spec.url)
    try:
        outcomes = render_states(
            browser, spec.url, spec.recipe, ctx.render, lambda: ctx.pace.wait(host)
        )
    except PlaywrightError as exc:
        # render_states reports a failed state itself. What reaches here is the browser: it could
        # not open a context or a page, or it died (a disconnected browser is re-raised).
        return _for_every_state(spec, CaptureStatus.BROWSER_UNAVAILABLE, _first_line(exc))
    results: list[CaptureResult] = []
    for outcome in outcomes:
        if not isinstance(outcome, RenderedState):
            results.append(
                CaptureResult(spec.key, outcome.label, method, outcome.status, outcome.detail, None)
            )
            continue
        if not is_http_url(outcome.final_url):
            # A page the browser could not open ends on its own error page
            # (chrome-error://chromewebdata/), whose text is not the vendor's.
            results.append(
                CaptureResult(
                    spec.key,
                    outcome.label,
                    method,
                    CaptureStatus.HTTP_ERROR,
                    "the browser showed an error page",
                    None,
                )
            )
            continue
        blocked = _redirect_block(spec, ctx, outcome.final_url)
        if blocked is not None:
            results.append(
                CaptureResult(
                    spec.key, outcome.label, method, CaptureStatus.BLOCKED_BY_ROBOTS, blocked, None
                )
            )
            continue
        if len(outcome.html.encode("utf-8")) > MAX_PAGE_BYTES:
            results.append(
                CaptureResult(
                    spec.key,
                    outcome.label,
                    method,
                    CaptureStatus.TOO_LARGE,
                    f"the rendered page is larger than {MAX_PAGE_BYTES} bytes",
                    None,
                )
            )
            continue
        ref = write_snapshot(
            ctx.snapshots_root,
            SnapshotInput(
                run_id=ctx.run_id,
                page_key=spec.key,
                state_label=outcome.label,
                url=spec.url,
                final_url=outcome.final_url,
                http_status=outcome.status,
                method=method,
                captured_at=ctx.now(),
                html=outcome.html,
                raw_bytes=None,
                encoding=None,
                text=outcome.visible_text,
                structured=extract_structured(outcome.html),
                screenshot_png=outcome.screenshot_png,
                locale=detect_locale_markers(outcome.html, outcome.visible_text, outcome.headers),
                collection_country=ctx.collection_country,
            ),
        )
        status, detail = _status_for(outcome.status, outcome.html)
        results.append(CaptureResult(spec.key, outcome.label, method, status, detail, ref))
    return results
