from __future__ import annotations

import socket
import time

import pytest

from mihenk.capture.browser import LaunchedBrowser
from mihenk.capture.models import CaptureStatus, Method
from mihenk.capture.recipe import ClickSelector, ClickText, Recipe, SelectOption, State
from mihenk.capture.render import RenderedState, RenderSettings, StateFailure, render_states
from tests.helpers.pages import load_expectations, serve_page
from tests.helpers.site import LocalSite

pytestmark = pytest.mark.browser


def _no_pacing() -> None:
    """A `before_navigation` that does nothing."""


def _closed_local_url() -> str:
    """A 127.0.0.1 address with nothing listening: connecting is refused at once."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}/"


def _single(recipe_method: Method = Method.RENDER) -> Recipe:
    return Recipe(method=recipe_method, states=[State(label="default")])


def _toggle_recipe() -> Recipe:
    """The `billing-toggle` recipe, built from the page's own expectations."""
    states = load_expectations("billing-toggle")["states"]
    return Recipe.model_validate(
        {
            "method": "render_interact",
            "states": [{"label": s["label"], "actions": s["actions"]} for s in states],
        }
    )


def _rendered(result: RenderedState | StateFailure) -> RenderedState:
    assert isinstance(result, RenderedState), result
    return result


def _failure(result: RenderedState | StateFailure) -> StateFailure:
    assert isinstance(result, StateFailure), result
    return result


def test_js_only_prices_need_render(site: LocalSite, browser: LaunchedBrowser) -> None:
    url = serve_page(site, "js-only-prices")
    results = render_states(browser.browser, url, _single(), RenderSettings(), _no_pacing)
    assert len(results) == 1
    state = _rendered(results[0])
    for expected in load_expectations("js-only-prices")["render_text_contains"]:
        assert expected in state.visible_text
    assert "Loading plans" not in state.visible_text


def test_rendered_state_carries_the_response_and_a_screenshot(
    site: LocalSite, browser: LaunchedBrowser
) -> None:
    url = serve_page(site, "billing-toggle")
    state = _rendered(
        render_states(browser.browser, url, _single(), RenderSettings(), _no_pacing)[0]
    )
    assert state.label == "default"
    assert state.final_url == url
    assert state.status == 200
    assert state.headers["content-type"] == "text/html; charset=utf-8"
    assert "<title>Contoso CRM pricing</title>" in state.html
    assert state.visible_text.endswith("\n")
    assert state.screenshot_png.startswith(b"\x89PNG\r\n\x1a\n")


def test_final_url_follows_a_redirect(site: LocalSite, browser: LaunchedBrowser) -> None:
    target = serve_page(site, "billing-toggle")
    site.redirect("/old-pricing", "/billing-toggle")
    state = _rendered(
        render_states(
            browser.browser, site.url("/old-pricing"), _single(), RenderSettings(), _no_pacing
        )[0]
    )
    assert state.final_url == target
    assert state.status == 200


def test_an_error_status_is_reported_not_raised(site: LocalSite, browser: LaunchedBrowser) -> None:
    url = serve_page(site, "bot-wall")
    state = _rendered(
        render_states(browser.browser, url, _single(), RenderSettings(), _no_pacing)[0]
    )
    assert state.status == 403
    assert "One moment, please" in state.visible_text


def test_billing_toggle_states(site: LocalSite, browser: LaunchedBrowser) -> None:
    url = serve_page(site, "billing-toggle")
    results = render_states(browser.browser, url, _toggle_recipe(), RenderSettings(), _no_pacing)
    assert [result.label for result in results] == ["annual", "monthly"]
    annual, monthly = (_rendered(result) for result in results)
    assert "€24 / month, billed yearly" in annual.visible_text
    assert "billed monthly" not in annual.visible_text
    assert "€29 / month, billed monthly" in monthly.visible_text
    assert "billed yearly" not in monthly.visible_text


def test_each_state_starts_from_a_fresh_navigation(
    site: LocalSite, browser: LaunchedBrowser
) -> None:
    # The "annual" state comes after nothing, and "again" after "monthly" has clicked its button:
    # it must show the annual price, so the page was loaded again rather than reused.
    url = serve_page(site, "billing-toggle")
    recipe = Recipe(
        method=Method.RENDER_INTERACT,
        states=[
            State(label="monthly", actions=[ClickText(text="Monthly")]),
            State(label="again"),
        ],
    )
    monthly, again = (
        _rendered(result)
        for result in render_states(browser.browser, url, recipe, RenderSettings(), _no_pacing)
    )
    assert "billed monthly" in monthly.visible_text
    assert "billed yearly" in again.visible_text
    assert site.hits.count("/billing-toggle") == 2


def test_selector_and_select_actions(site: LocalSite, browser: LaunchedBrowser) -> None:
    site.add(
        "/controls",
        """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Controls</title></head>
<body>
<button id="more" type="button">Show more</button>
<select id="region"><option value="eu">EU</option><option value="us">US</option></select>
<p id="out">start</p>
<script>
var out = document.getElementById("out");
document.getElementById("more").addEventListener("click", function () {
  out.textContent = "expanded";
});
document.getElementById("region").addEventListener("change", function (event) {
  out.textContent = "region " + event.target.value;
});
</script>
</body></html>""",
    )
    recipe = Recipe(
        method=Method.RENDER_INTERACT,
        states=[
            State(label="start"),
            State(label="expanded", actions=[ClickSelector(selector="#more")]),
            State(label="us", actions=[SelectOption(selector="#region", value="us")]),
        ],
    )
    results = render_states(
        browser.browser, site.url("/controls"), recipe, RenderSettings(), _no_pacing
    )
    texts = {result.label: _rendered(result).visible_text for result in results}
    assert "start" in texts["start"]
    assert "expanded" in texts["expanded"]
    assert "region us" in texts["us"]


def test_render_finishes_on_never_idle_page(site: LocalSite, browser: LaunchedBrowser) -> None:
    url = serve_page(site, "never-idle")
    settings = RenderSettings(idle_cap_s=2.0)
    started = time.monotonic()
    results = render_states(browser.browser, url, _single(), settings, _no_pacing)
    elapsed = time.monotonic() - started
    assert elapsed < 15
    assert elapsed < settings.navigation_timeout_s
    state = _rendered(results[0])
    for expected in load_expectations("never-idle")["render_text_contains"]:
        assert expected in state.visible_text


def test_missing_toggle_is_an_action_failure(site: LocalSite, browser: LaunchedBrowser) -> None:
    url = serve_page(site, "billing-toggle")
    recipe = Recipe(
        method=Method.RENDER_INTERACT,
        states=[
            State(label="annual"),
            State(label="quarterly", actions=[ClickText(text="Quarterly")]),
            State(label="monthly", actions=[ClickText(text="Monthly")]),
        ],
    )
    results = render_states(
        browser.browser, url, recipe, RenderSettings(navigation_timeout_s=5.0), _no_pacing
    )
    assert [result.label for result in results] == ["annual", "quarterly", "monthly"]
    assert "billed yearly" in _rendered(results[0]).visible_text
    failure = _failure(results[1])
    assert failure.status is CaptureStatus.ACTION_FAILED
    assert "click_text" in failure.detail
    assert "billed monthly" in _rendered(results[2]).visible_text


def test_a_slow_page_is_a_timeout(site: LocalSite, browser: LaunchedBrowser) -> None:
    site.add("/slow", "<p>too late</p>", delay_s=3.0)
    results = render_states(
        browser.browser,
        site.url("/slow"),
        _single(),
        RenderSettings(navigation_timeout_s=1.0),
        _no_pacing,
    )
    failure = _failure(results[0])
    assert failure.label == "default"
    assert failure.status is CaptureStatus.TIMEOUT


def test_a_refused_connection_is_an_http_error_not_an_exception(browser: LaunchedBrowser) -> None:
    recipe = Recipe(
        method=Method.RENDER_INTERACT,
        states=[State(label="first"), State(label="second")],
    )
    results = render_states(
        browser.browser, _closed_local_url(), recipe, RenderSettings(), _no_pacing
    )
    assert [result.label for result in results] == ["first", "second"]
    for result in results:
        assert _failure(result).status is CaptureStatus.HTTP_ERROR


def test_a_failed_state_does_not_stop_the_next_one(
    site: LocalSite, browser: LaunchedBrowser
) -> None:
    # The first navigation is sent to a closed port, the second to a real page.
    page_url = serve_page(site, "billing-toggle")
    closed = _closed_local_url()
    calls = 0

    def route_the_next_navigation() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            site.redirect("/r", closed)
        else:
            site.redirect("/r", "/billing-toggle")

    recipe = Recipe(
        method=Method.RENDER_INTERACT,
        states=[State(label="refused"), State(label="fine")],
    )
    results = render_states(
        browser.browser, site.url("/r"), recipe, RenderSettings(), route_the_next_navigation
    )
    assert _failure(results[0]).status is CaptureStatus.HTTP_ERROR
    assert _rendered(results[1]).final_url == page_url


def test_before_navigation_is_called_per_state(site: LocalSite, browser: LaunchedBrowser) -> None:
    url = serve_page(site, "billing-toggle")
    page_hits_at_each_call: list[int] = []

    def record() -> None:
        page_hits_at_each_call.append(site.hits.count("/billing-toggle"))

    results = render_states(browser.browser, url, _toggle_recipe(), RenderSettings(), record)
    assert len(results) == 2
    # Called once before each state's navigation, never after it.
    assert page_hits_at_each_call == [0, 1]


def test_each_call_uses_a_fresh_context(site: LocalSite, browser: LaunchedBrowser) -> None:
    site.add(
        "/cookie",
        """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Cookie</title></head>
<body><p id="out"></p>
<script>
var out = document.getElementById("out");
var before = document.cookie;
document.cookie = "seen=1; path=/";
out.textContent = "before=[" + before + "] after=[" + document.cookie + "]";
</script></body></html>""",
    )
    url = site.url("/cookie")
    first = _rendered(
        render_states(browser.browser, url, _single(), RenderSettings(), _no_pacing)[0]
    )
    second = _rendered(
        render_states(browser.browser, url, _single(), RenderSettings(), _no_pacing)[0]
    )
    # The page can set a cookie (so the test could notice one carried over) ...
    assert "after=[seen=1]" in first.visible_text
    # ... and neither call starts with the other's cookie.
    assert "before=[]" in first.visible_text
    assert "before=[]" in second.visible_text


def test_a_lone_surrogate_in_the_page_does_not_reach_the_snapshot(
    site: LocalSite, browser: LaunchedBrowser
) -> None:
    site.add(
        "/surrogate",
        """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Surrogate</title></head>
<body><p id="out">placeholder</p>
<script>
document.getElementById("out").textContent = "price \\ud83d 9";
</script></body></html>""",
    )
    state = _rendered(
        render_states(
            browser.browser, site.url("/surrogate"), _single(), RenderSettings(), _no_pacing
        )[0]
    )
    # Writing a snapshot encodes both as UTF-8, which refuses a lone surrogate. (Chrome 154 may
    # already replace it before Playwright hands it over; tests/unit/test_render_fakes.py pins
    # the replacement itself.)
    state.html.encode("utf-8")
    state.visible_text.encode("utf-8")
    assert "price \ufffd 9" in state.visible_text
    assert "\ufffd" in state.html
