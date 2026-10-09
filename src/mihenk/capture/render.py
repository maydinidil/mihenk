"""Rendering pages in the installed browser (design §8.3).

Each call opens a fresh browser context (no cookies carried over, downloads off) and closes
it. Each state is a fresh page and navigation followed by its actions. Pages that never go
network-idle are normal: the idle wait is capped and the capture continues. A browser error
in one state (a timeout, a refused connection, an aborted navigation) is that state's
`StateFailure`; the next state still runs.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from playwright.sync_api import Browser, Page
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from mihenk.capture.models import CaptureStatus
from mihenk.capture.recipe import Action, ClickSelector, ClickText, Recipe, SelectOption, State
from mihenk.trim.text import canonical_text


@dataclass(frozen=True)
class RenderSettings:
    navigation_timeout_s: float = 30.0
    idle_cap_s: float = 5.0
    settle_s: float = 0.5
    locale: str = "en-GB"


@dataclass(frozen=True)
class RenderedState:
    label: str
    final_url: str
    status: int | None
    headers: Mapping[str, str]
    html: str
    visible_text: str
    screenshot_png: bytes


@dataclass(frozen=True)
class StateFailure:
    label: str
    status: CaptureStatus
    detail: str


class _ActionFailed(Exception):
    pass


# A rendered DOM can hold half of a surrogate pair. Writing it into a snapshot would raise
# `UnicodeEncodeError`, so it becomes U+FFFD, which is what a UTF-8 decoder would show.
_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def _replace_lone_surrogates(text: str) -> str:
    return _LONE_SURROGATE.sub("\ufffd", text)


def _settle(page: Page, settings: RenderSettings) -> None:
    with contextlib.suppress(PlaywrightTimeoutError):
        page.wait_for_load_state("networkidle", timeout=settings.idle_cap_s * 1000)
    # Best effort: there may be no body, or a navigation may be in flight.
    with contextlib.suppress(PlaywrightError):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(settings.settle_s * 1000)


def _perform(page: Page, action: Action) -> None:
    try:
        match action:
            case ClickText(text=text, exact=exact):
                page.get_by_text(text, exact=exact).first.click()
            case ClickSelector(selector=selector):
                page.locator(selector).first.click()
            case SelectOption(selector=selector, value=value):
                page.locator(selector).first.select_option(value)
    except PlaywrightError as exc:
        raise _ActionFailed(f"{action.kind}: {exc}") from exc


def _capture_state(page: Page, url: str, state: State, settings: RenderSettings) -> RenderedState:
    response = page.goto(url, wait_until="domcontentloaded")
    _settle(page, settings)
    for action in state.actions:
        _perform(page, action)
        _settle(page, settings)
    return RenderedState(
        label=state.label,
        final_url=page.url,
        status=response.status if response is not None else None,
        headers=dict(response.headers) if response is not None else {},
        html=_replace_lone_surrogates(page.content()),
        visible_text=canonical_text(_replace_lone_surrogates(page.inner_text("body"))),
        screenshot_png=page.screenshot(full_page=True),
    )


def render_states(
    browser: Browser,
    url: str,
    recipe: Recipe,
    settings: RenderSettings,
    before_navigation: Callable[[], object],
) -> list[RenderedState | StateFailure]:
    context = browser.new_context(accept_downloads=False, locale=settings.locale)
    results: list[RenderedState | StateFailure] = []
    try:
        for state in recipe.states:
            before_navigation()
            # One page per state, in the shared context. Chrome commits the error page of a
            # failed navigation late, and that interrupts the next navigation on the same page.
            page = context.new_page()
            page.set_default_timeout(settings.navigation_timeout_s * 1000)
            try:
                results.append(_capture_state(page, url, state, settings))
            except _ActionFailed as exc:
                results.append(StateFailure(state.label, CaptureStatus.ACTION_FAILED, str(exc)))
            except PlaywrightTimeoutError as exc:
                results.append(StateFailure(state.label, CaptureStatus.TIMEOUT, str(exc)))
            except PlaywrightError as exc:
                # Connection refused, a name that does not resolve, an aborted navigation.
                results.append(StateFailure(state.label, CaptureStatus.HTTP_ERROR, str(exc)))
            finally:
                with contextlib.suppress(PlaywrightError):
                    page.close()
    finally:
        context.close()
    return results
