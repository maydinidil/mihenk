"""render_states against a stand-in browser, for what a real Chrome will not produce on demand.

Chrome 154 already replaces a lone surrogate with U+FFFD before Playwright hands the text over,
and a browser that dies mid-capture cannot be arranged reliably, so these behaviours are pinned
here. The browser tests in tests/integration/test_render.py cover the real thing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import pytest
from playwright.sync_api import Browser
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from mihenk.capture.models import CaptureStatus, Method
from mihenk.capture.recipe import Recipe, State
from mihenk.capture.render import RenderedState, RenderSettings, StateFailure, render_states


class _Response:
    status = 200
    headers: dict[str, str] = {}  # noqa: RUF012 - read-only stand-in


class _Root:
    def __init__(self, page: _Page) -> None:
        self._page = page

    def evaluate(self, expression: str, *, timeout: float) -> str:
        if self._page.read_error is not None:
            raise self._page.read_error
        return self._page.html


class _Page:
    url = "http://example.invalid/pricing"

    def __init__(
        self,
        *,
        html: str = "<p>ok</p>",
        text: str = "ok",
        scroll_fails: bool = False,
        goto_error: BaseException | None = None,
        read_error: Exception | None = None,
        close_error: Exception | None = None,
        popups: int = 0,
    ) -> None:
        self.html = html
        self._text = text
        self._scroll_fails = scroll_fails
        self._goto_error = goto_error
        self.read_error = read_error
        self._close_error = close_error
        self._popups = popups
        self.context: _Context | None = None
        self.closed = False
        self.close_calls = 0
        self.handlers: dict[str, Callable[..., object]] = {}

    def on(self, event: str, handler: Callable[..., object]) -> None:
        self.handlers[event] = handler

    def set_default_timeout(self, timeout: float) -> None:
        pass

    def goto(self, url: str, *, wait_until: str) -> _Response:
        if self._goto_error is not None:
            raise self._goto_error
        if self.context is not None:
            for _ in range(self._popups):  # a window.open() or a target=_blank link
                self.context.open_popup()
        return _Response()

    def wait_for_function(self, expression: str, *, timeout: float) -> None:
        if self._scroll_fails:
            raise PlaywrightError("Execution context was destroyed")

    def wait_for_timeout(self, timeout: float) -> None:
        pass

    def locator(self, selector: str) -> _Root:
        return _Root(self)

    def inner_text(self, selector: str) -> str:
        return self._text

    def screenshot(self, *, full_page: bool) -> bytes:
        return b"png"

    def close(self) -> None:
        self.close_calls += 1
        if self._close_error is not None:
            raise self._close_error
        self.closed = True


class _Context:
    def __init__(
        self,
        page: _Page,
        *,
        close_error: Exception | None = None,
        new_page_error: Exception | None = None,
    ) -> None:
        self._page = page
        self._close_error = close_error
        self._new_page_error = new_page_error
        self._opened: list[_Page] = []
        self.popups: list[_Page] = []
        self.open_at_new_page: list[int] = []  # how many pages were open as each state began
        self.close_calls = 0

    @property
    def closed(self) -> bool:
        return self.close_calls > 0

    @property
    def pages(self) -> list[_Page]:
        """The pages that are open, as Playwright's `context.pages` lists them."""
        return [page for page in self._opened if not page.closed]

    def new_page(self) -> _Page:
        self.open_at_new_page.append(len(self.pages))
        if self._new_page_error is not None:
            raise self._new_page_error
        # The same stand-in serves every state, so it is "reopened" for each one.
        self._page.closed = False
        self._page.context = self
        if self._page not in self._opened:
            self._opened.append(self._page)
        return self._page

    def open_popup(self) -> None:
        popup = _Page()
        popup.context = self
        self.popups.append(popup)
        self._opened.append(popup)

    def close(self) -> None:
        self.close_calls += 1
        if self._close_error is not None:
            raise self._close_error


class _Browser:
    def __init__(
        self,
        page: _Page,
        *,
        connected: bool = True,
        close_error: Exception | None = None,
        new_page_error: Exception | None = None,
    ) -> None:
        self.context = _Context(page, close_error=close_error, new_page_error=new_page_error)
        self.connected = connected
        self.context_options: dict[str, Any] = {}

    def is_connected(self) -> bool:
        return self.connected

    def new_context(self, **options: Any) -> _Context:
        self.context_options = options
        return self.context


def _render(
    browser: _Browser,
    recipe: Recipe | None = None,
    before_navigation: Callable[[], object] = dict,
) -> list[RenderedState | StateFailure]:
    recipe = recipe or Recipe(method=Method.RENDER, states=[State(label="default")])
    return render_states(
        cast(Browser, browser),
        "http://example.invalid/pricing",
        recipe,
        RenderSettings(),
        before_navigation,
    )


def test_lone_surrogates_become_replacement_characters() -> None:
    browser = _Browser(_Page(html="<p>price \ud83d 9</p>", text="price \ud83d 9\n"))
    state = _render(browser)[0]
    assert isinstance(state, RenderedState)
    assert state.html == "<p>price \ufffd 9</p>"
    assert state.visible_text == "price \ufffd 9\n"
    state.html.encode("utf-8")
    state.visible_text.encode("utf-8")
    assert browser.context.closed


def test_a_real_emoji_is_kept() -> None:
    state = _render(_Browser(_Page(html="<p>\U0001f600</p>", text="\U0001f600\n")))[0]
    assert isinstance(state, RenderedState)
    assert state.html == "<p>\U0001f600</p>"
    assert state.visible_text == "\U0001f600\n"


def test_a_failing_scroll_does_not_fail_the_state() -> None:
    state = _render(_Browser(_Page(text="ok", scroll_fails=True)))[0]
    assert isinstance(state, RenderedState)
    assert state.visible_text == "ok\n"


def test_a_timeout_reading_the_page_is_a_timeout_failure() -> None:
    page = _Page(read_error=PlaywrightTimeoutError("Locator.evaluate: Timeout 5000ms exceeded."))
    failure = _render(_Browser(page))[0]
    assert isinstance(failure, StateFailure)
    assert failure.status is CaptureStatus.TIMEOUT


def test_the_context_blocks_downloads_and_service_workers() -> None:
    browser = _Browser(_Page())
    _render(browser)
    assert browser.context_options["accept_downloads"] is False
    assert browser.context_options["service_workers"] == "block"


def test_a_browser_error_while_connected_is_an_http_error() -> None:
    browser = _Browser(_Page(goto_error=PlaywrightError("net::ERR_CONNECTION_REFUSED")))
    failure = _render(browser)[0]
    assert isinstance(failure, StateFailure)
    assert failure.status is CaptureStatus.HTTP_ERROR


def test_a_browser_that_died_is_not_recorded_as_an_http_error() -> None:
    browser = _Browser(
        _Page(goto_error=PlaywrightError("Target page, context or browser has been closed")),
        connected=False,
    )
    with pytest.raises(PlaywrightError, match="has been closed"):
        _render(browser)
    assert browser.context.closed


# --- cleanup: what is closed, and when ------------------------------------------------------------


@pytest.mark.parametrize("leaving", [KeyboardInterrupt(), SystemExit(1)])
def test_ctrl_c_in_a_state_closes_nothing(leaving: BaseException) -> None:
    # Playwright's sync calls hang while a KeyboardInterrupt or SystemExit is in flight, and the
    # process is leaving anyway.
    page = _Page(goto_error=leaving)
    browser = _Browser(page)
    with pytest.raises(type(leaving)):
        _render(browser)
    assert page.close_calls == 0
    assert browser.context.close_calls == 0


def test_ctrl_c_while_waiting_to_start_a_state_closes_nothing() -> None:
    def interrupted() -> None:
        raise KeyboardInterrupt

    browser = _Browser(_Page())
    with pytest.raises(KeyboardInterrupt):
        _render(browser, before_navigation=interrupted)
    assert browser.context.close_calls == 0


def test_a_close_error_does_not_replace_the_error_in_flight() -> None:
    page = _Page(
        goto_error=PlaywrightError("Target page, context or browser has been closed"),
        close_error=PlaywrightError("page close failed"),
    )
    browser = _Browser(page, connected=False, close_error=PlaywrightError("context close failed"))
    with pytest.raises(PlaywrightError, match="has been closed"):
        _render(browser)
    assert page.close_calls == 1  # both were tried, and both errors were left unheard
    assert browser.context.close_calls == 1


def test_a_context_close_error_does_not_replace_an_error_outside_the_browser() -> None:
    def broken() -> None:
        raise RuntimeError("the pace gave up")

    browser = _Browser(_Page(), close_error=PlaywrightError("context close failed"))
    with pytest.raises(RuntimeError, match="the pace gave up"):
        _render(browser, before_navigation=broken)
    assert browser.context.close_calls == 1


def test_a_page_close_error_with_nothing_in_flight_propagates() -> None:
    page = _Page(close_error=PlaywrightError("page close failed"))
    browser = _Browser(page)
    with pytest.raises(PlaywrightError, match="page close failed"):
        _render(browser)
    assert browser.context.close_calls == 1  # the context is still closed


def test_a_context_close_error_with_nothing_in_flight_propagates() -> None:
    page = _Page()
    browser = _Browser(page, close_error=PlaywrightError("context close failed"))
    with pytest.raises(PlaywrightError, match="context close failed"):
        _render(browser)
    assert page.close_calls == 1


# --- pages the page opens -------------------------------------------------------------------------


def test_pages_a_state_opened_are_closed_after_that_state() -> None:
    page = _Page(popups=2)
    browser = _Browser(page)
    recipe = Recipe(
        method=Method.RENDER_INTERACT, states=[State(label="first"), State(label="second")]
    )
    results = _render(browser, recipe)
    assert all(isinstance(result, RenderedState) for result in results)
    assert len(browser.context.popups) == 4  # two for each state
    assert all(popup.closed for popup in browser.context.popups)
    # Nothing from the first state was still running when the second began.
    assert browser.context.open_at_new_page == [0, 0]


def test_pages_a_failed_state_opened_are_closed_too() -> None:
    page = _Page(popups=1, read_error=PlaywrightTimeoutError("Locator.evaluate: Timeout"))
    browser = _Browser(page)
    failure = _render(browser)[0]
    assert isinstance(failure, StateFailure)
    assert len(browser.context.popups) == 1
    assert browser.context.pages == []


# --- closing on the failure paths -----------------------------------------------------------------


def test_the_page_is_closed_when_goto_raises() -> None:
    page = _Page(goto_error=PlaywrightError("net::ERR_CONNECTION_REFUSED"))
    failure = _render(_Browser(page))[0]
    assert isinstance(failure, StateFailure)
    assert page.close_calls == 1
    assert page.closed


def test_the_context_is_closed_when_a_state_fails() -> None:
    browser = _Browser(_Page(read_error=PlaywrightTimeoutError("Locator.evaluate: Timeout")))
    assert isinstance(_render(browser)[0], StateFailure)
    assert browser.context.close_calls == 1


def test_the_context_is_closed_when_the_browser_error_leaves_render_states() -> None:
    browser = _Browser(_Page(goto_error=PlaywrightError("net::ERR_ABORTED")), connected=False)
    with pytest.raises(PlaywrightError, match="ERR_ABORTED"):
        _render(browser)
    assert browser.context.close_calls == 1


def test_the_context_is_closed_when_new_page_raises() -> None:
    browser = _Browser(_Page(), new_page_error=PlaywrightError("Target closed"))
    with pytest.raises(PlaywrightError, match="Target closed"):
        _render(browser)
    assert browser.context.close_calls == 1
