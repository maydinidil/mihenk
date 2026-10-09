"""Rendering pages in the installed browser (design §8.3).

Each call opens a fresh browser context (no cookies carried over, downloads off, no service
workers) and closes it. Each state is a fresh page and navigation followed by its actions. Pages
that never go network-idle are normal: the wait for quiet is capped and the capture continues. A
browser error in one state (a timeout, a refused connection, an aborted navigation) is that
state's `StateFailure`; the next state still runs.

Every call that reads the page carries a timeout, so a page that spins forever in JavaScript is a
`TIMEOUT` and not a hang.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass

from playwright.sync_api import Browser, BrowserContext, Dialog, Page, Request, Response
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from mihenk.capture.models import CaptureStatus
from mihenk.capture.recipe import Action, ClickSelector, ClickText, Recipe, SelectOption, State
from mihenk.trim.text import canonical_text, scrub_surrogates


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


# How long no request may start or finish before the page counts as quiet (Playwright's own
# "networkidle" uses the same 500 ms), and how often the wait looks again.
_QUIET_S = 0.5
_POLL_S = 0.1
# The scroll that wakes lazy loading is best effort, so it gives up sooner than a read does.
_SCROLL_TIMEOUT_S = 2.0
_SCROLL_JS = (
    "() => { window.scrollTo(0, document.body ? document.body.scrollHeight : 0); return true; }"
)
# What `page.content()` reads, through a call that has a timeout.
_HTML_JS = """(root) => {
  const doc = root.ownerDocument;
  const doctype = doc.doctype ? new XMLSerializer().serializeToString(doc.doctype) : "";
  return doctype + root.outerHTML;
}"""


def _dismiss(dialog: Dialog) -> None:
    # Playwright dismisses dialogs itself when nobody listens, but a page that opens one in a
    # loop can then crash the driver while the page is closing. Doing it here is safe.
    with contextlib.suppress(PlaywrightError):
        dialog.dismiss()


class _PageWatch:
    """What the page reports while it is driven: requests in flight and the last navigation.

    Registered before the first navigation. `networkidle` fires once per document, so it says
    nothing about a request that a click starts; counting the requests does.
    """

    def __init__(self, page: Page) -> None:
        self._page = page
        self._in_flight: set[Request] = set()
        self.last_activity = time.monotonic()
        self.navigation: Response | None = None
        page.on("request", self._started)
        page.on("requestfinished", self._ended)
        page.on("requestfailed", self._ended)
        page.on("response", self._responded)
        page.on("dialog", _dismiss)

    @property
    def busy(self) -> bool:
        return bool(self._in_flight)

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    def _started(self, request: Request) -> None:
        self._in_flight.add(request)
        self.touch()

    def _ended(self, request: Request) -> None:
        self._in_flight.discard(request)
        self.touch()

    def _responded(self, response: Response) -> None:
        # The last answer to a navigation of the page itself: a reload or a click that opens
        # another page replaces the first one. Frames and subresources do not count.
        with contextlib.suppress(PlaywrightError):
            if response.request.is_navigation_request() and response.frame == self._page.main_frame:
                self.navigation = response


def _settle(page: Page, watch: _PageWatch, settings: RenderSettings) -> None:
    """Wait until no request has been in flight for 500 ms, but at most `idle_cap_s`."""
    watch.touch()  # an action's own request may not have been reported yet
    deadline = time.monotonic() + settings.idle_cap_s
    while True:
        now = time.monotonic()
        if not watch.busy and now - watch.last_activity >= _QUIET_S:
            break
        if now >= deadline:
            break
        page.wait_for_timeout(_POLL_S * 1000)
    # Best effort: there may be no body, the page may be busy, or a navigation may be in flight.
    with contextlib.suppress(PlaywrightError):
        page.wait_for_function(_SCROLL_JS, timeout=_SCROLL_TIMEOUT_S * 1000)
    page.wait_for_timeout(settings.settle_s * 1000)


def _perform(page: Page, action: Action) -> None:
    # `.first` of the visible matches: sites ship a hidden mobile and desktop copy of a toggle,
    # and the hidden one may come first in the page.
    try:
        match action:
            case ClickText(text=text, exact=exact):
                page.get_by_text(text, exact=exact).filter(visible=True).first.click()
            case ClickSelector(selector=selector):
                page.locator(selector).filter(visible=True).first.click()
            case SelectOption(selector=selector, value=value):
                page.locator(selector).filter(visible=True).first.select_option(value)
    except PlaywrightError as exc:
        raise _ActionFailed(f"{action.kind}: {exc}") from exc


def _capture_state(page: Page, url: str, state: State, settings: RenderSettings) -> RenderedState:
    watch = _PageWatch(page)
    first = page.goto(url, wait_until="domcontentloaded")
    _settle(page, watch, settings)
    for action in state.actions:
        _perform(page, action)
        _settle(page, watch, settings)
    html = page.locator(":root").evaluate(_HTML_JS, timeout=settings.navigation_timeout_s * 1000)
    response = watch.navigation or first
    return RenderedState(
        label=state.label,
        final_url=page.url,
        status=response.status if response is not None else None,
        headers=dict(response.headers) if response is not None else {},
        html=scrub_surrogates(html),
        visible_text=canonical_text(scrub_surrogates(page.inner_text("body"))),
        screenshot_png=page.screenshot(full_page=True),
    )


@contextlib.contextmanager
def _then_close(close: Callable[[], object]) -> Iterator[None]:
    """Runs `close` after the block, by three rules for what is in flight when the block ends.

    - Nothing: `close` runs and its error propagates (the caller maps it to `browser_unavailable`).
    - An `Exception`: `close` runs, and an error from it is dropped so that it cannot replace the
      one in flight.
    - Any other `BaseException` (`KeyboardInterrupt`, `SystemExit`): `close` does not run.
      Playwright's sync calls hang in that state, and the process is leaving anyway.
    """
    try:
        yield
    except Exception:
        with contextlib.suppress(Exception):
            close()
        raise
    except BaseException:
        raise
    else:
        close()


def _close_pages(context: BrowserContext) -> None:
    """Closes every page of the context: the state's own and any that the page opened (a
    `window.open` or a `target=_blank` link), which would otherwise keep running unpaced."""
    for page in list(context.pages):
        page.close()


def render_states(
    browser: Browser,
    url: str,
    recipe: Recipe,
    settings: RenderSettings,
    before_navigation: Callable[[], object],
) -> list[RenderedState | StateFailure]:
    context = browser.new_context(
        accept_downloads=False, locale=settings.locale, service_workers="block"
    )
    results: list[RenderedState | StateFailure] = []
    with _then_close(context.close):
        for state in recipe.states:
            before_navigation()
            with _then_close(lambda: _close_pages(context)):
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
                    if not browser.is_connected():
                        raise  # A browser that died is not the vendor's HTTP error.
                    # Connection refused, a name that does not resolve, an aborted navigation.
                    results.append(StateFailure(state.label, CaptureStatus.HTTP_ERROR, str(exc)))
    return results
