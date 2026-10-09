"""render_states against a stand-in browser, for what a real Chrome will not produce on demand.

Chrome 154 already replaces a lone surrogate with U+FFFD before Playwright hands the text over,
and a page whose body vanishes mid-navigation cannot be timed reliably, so these two behaviours
are pinned here. The browser tests in tests/integration/test_render.py cover the real thing.
"""

from __future__ import annotations

from typing import Any, cast

from playwright.sync_api import Browser
from playwright.sync_api import Error as PlaywrightError

from mihenk.capture.models import Method
from mihenk.capture.recipe import Recipe, State
from mihenk.capture.render import RenderedState, RenderSettings, render_states


class _Response:
    status = 200
    headers: dict[str, str] = {}  # noqa: RUF012 - read-only stand-in


class _Page:
    url = "http://example.invalid/pricing"

    def __init__(self, *, html: str, text: str, scroll_fails: bool = False) -> None:
        self._html = html
        self._text = text
        self._scroll_fails = scroll_fails

    def set_default_timeout(self, timeout: float) -> None:
        pass

    def goto(self, url: str, *, wait_until: str) -> _Response:
        return _Response()

    def wait_for_load_state(self, state: str, *, timeout: float) -> None:
        pass

    def evaluate(self, expression: str) -> None:
        if self._scroll_fails:
            raise PlaywrightError("Execution context was destroyed")

    def wait_for_timeout(self, timeout: float) -> None:
        pass

    def content(self) -> str:
        return self._html

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
    def __init__(self, page: _Page) -> None:
        self.context = _Context(page)

    def new_context(self, **options: Any) -> _Context:
        return self.context


def _render(page: _Page) -> tuple[list[Any], _Browser]:
    browser = _Browser(page)
    recipe = Recipe(method=Method.RENDER, states=[State(label="default")])
    results = render_states(
        cast(Browser, browser), "http://example.invalid/pricing", recipe, RenderSettings(), dict
    )
    return results, browser


def test_lone_surrogates_become_replacement_characters() -> None:
    page = _Page(html="<p>price \ud83d 9</p>", text="price \ud83d 9\n")
    results, browser = _render(page)
    state = results[0]
    assert isinstance(state, RenderedState)
    assert state.html == "<p>price \ufffd 9</p>"
    assert state.visible_text == "price \ufffd 9\n"
    state.html.encode("utf-8")
    state.visible_text.encode("utf-8")
    assert browser.context.closed


def test_a_real_emoji_is_kept() -> None:
    results, _ = _render(_Page(html="<p>\U0001f600</p>", text="\U0001f600\n"))
    state = results[0]
    assert isinstance(state, RenderedState)
    assert state.html == "<p>\U0001f600</p>"
    assert state.visible_text == "\U0001f600\n"


def test_a_failing_scroll_does_not_fail_the_state() -> None:
    results, _ = _render(_Page(html="<p>ok</p>", text="ok", scroll_fails=True))
    state = results[0]
    assert isinstance(state, RenderedState)
    assert state.visible_text == "ok\n"
