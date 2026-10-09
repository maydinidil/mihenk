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
        goto_error: Exception | None = None,
        read_error: Exception | None = None,
    ) -> None:
        self.html = html
        self._text = text
        self._scroll_fails = scroll_fails
        self._goto_error = goto_error
        self.read_error = read_error
        self.handlers: dict[str, Callable[..., object]] = {}

    def on(self, event: str, handler: Callable[..., object]) -> None:
        self.handlers[event] = handler

    def set_default_timeout(self, timeout: float) -> None:
        pass

    def goto(self, url: str, *, wait_until: str) -> _Response:
        if self._goto_error is not None:
            raise self._goto_error
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
        pass


class _Context:
    def __init__(self, page: _Page) -> None:
        self._page = page
        self.closed = False

    def new_page(self) -> _Page:
        return self._page

    def close(self) -> None:
        self.closed = True


class _Browser:
    def __init__(self, page: _Page, *, connected: bool = True) -> None:
        self.context = _Context(page)
        self.connected = connected
        self.context_options: dict[str, Any] = {}

    def is_connected(self) -> bool:
        return self.connected

    def new_context(self, **options: Any) -> _Context:
        self.context_options = options
        return self.context


def _render(browser: _Browser) -> list[RenderedState | StateFailure]:
    recipe = Recipe(method=Method.RENDER, states=[State(label="default")])
    return render_states(
        cast(Browser, browser), "http://example.invalid/pricing", recipe, RenderSettings(), dict
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
