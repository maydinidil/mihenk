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
    assert state.html.startswith("<!DOCTYPE html>")
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


def test_a_hidden_copy_of_a_control_does_not_catch_the_action(
    site: LocalSite, browser: LaunchedBrowser
) -> None:
    # Sites ship a mobile and a desktop copy of a toggle; the hidden one can come first. Every
    # action must reach the visible copy, which here shows the monthly price.
    site.add(
        "/two-copies",
        """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Two copies</title></head>
<body>
<div style="display: none">
<button class="plan-toggle" type="button">Monthly</button>
<select class="region"><option value="eu">EU</option><option value="us">US</option></select>
</div>
<div>
<button class="plan-toggle" type="button">Monthly</button>
<select class="region"><option value="eu">EU</option><option value="us">US</option></select>
</div>
<p id="out">annual price</p>
<script>
var out = document.getElementById("out");
var copies = document.querySelectorAll(".plan-toggle");
var hiddenCopy = copies[0], visibleCopy = copies[1];
hiddenCopy.addEventListener("click", function () { out.textContent = "WRONG hidden copy"; });
visibleCopy.addEventListener("click", function () { out.textContent = "monthly price"; });
var regions = document.querySelectorAll(".region");
regions[0].addEventListener("change", function () { out.textContent = "WRONG hidden region"; });
regions[1].addEventListener("change", function (event) {
  out.textContent = "region " + event.target.value;
});
</script>
</body></html>""",
    )
    recipe = Recipe(
        method=Method.RENDER_INTERACT,
        states=[
            State(label="by-text", actions=[ClickText(text="Monthly")]),
            State(label="by-selector", actions=[ClickSelector(selector=".plan-toggle")]),
            State(label="by-select", actions=[SelectOption(selector=".region", value="us")]),
        ],
    )
    # A short timeout: a click on the hidden copy waits for it to show, and gives up after this.
    results = render_states(
        browser.browser,
        site.url("/two-copies"),
        recipe,
        RenderSettings(navigation_timeout_s=3.0),
        _no_pacing,
    )
    texts = {result.label: _rendered(result).visible_text for result in results}
    assert "monthly price" in texts["by-text"]
    assert "monthly price" in texts["by-selector"]
    assert "region us" in texts["by-select"]
    assert not any("WRONG" in text for text in texts.values())


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


# A page that never gives control back must end as a TIMEOUT, not as a hang. The first spins in
# JavaScript after it has loaded; the second opens a dialog again and again.
SPINNING_PAGES = {
    "spin": "<!doctype html><title>Spin</title><p>hello</p>"
    "<script>setTimeout(function () { while (true) {} }, 300);</script>",
    "dialogs": "<!doctype html><title>Dialogs</title><p>hello</p>"
    "<script>window.addEventListener('load', function () {"
    " setTimeout(function () { while (true) { alert(1); } }, 300); });</script>",
}


@pytest.mark.parametrize("kind", sorted(SPINNING_PAGES))
def test_a_page_that_never_gives_control_back_is_a_timeout(
    kind: str, site: LocalSite, browser: LaunchedBrowser
) -> None:
    site.add(f"/{kind}", SPINNING_PAGES[kind])
    settings = RenderSettings(navigation_timeout_s=3.0, settle_s=0.1)
    started = time.monotonic()
    results = render_states(browser.browser, site.url(f"/{kind}"), _single(), settings, _no_pacing)
    elapsed = time.monotonic() - started
    assert _failure(results[0]).status is CaptureStatus.TIMEOUT
    assert elapsed < 30


def test_an_action_that_fetches_the_price_waits_for_the_answer(
    site: LocalSite, browser: LaunchedBrowser
) -> None:
    # The click starts a request that the server answers after 2 s; "networkidle" has fired
    # long before, so only counting the requests in flight sees it.
    site.add(
        "/lazy",
        """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Lazy</title></head>
<body><button id="m" type="button">Monthly</button>
<p id="price">€24 / month, billed yearly</p>
<script>
var price = document.getElementById("price");
document.getElementById("m").addEventListener("click", function () {
  price.textContent = "loading";
  fetch("/lazy-price").then(function (r) { return r.text(); }).then(function (t) {
    price.textContent = t;
  });
});
</script></body></html>""",
    )
    site.add(
        "/lazy-price",
        "€29 / month, billed monthly",
        content_type="text/plain; charset=utf-8",
        delay_s=2.0,
    )
    recipe = Recipe(
        method=Method.RENDER_INTERACT,
        states=[State(label="annual"), State(label="monthly", actions=[ClickText(text="Monthly")])],
    )
    results = render_states(
        browser.browser, site.url("/lazy"), recipe, RenderSettings(), _no_pacing
    )
    annual, monthly = (_rendered(result) for result in results)
    assert "€24 / month, billed yearly" in annual.visible_text
    assert "€29 / month, billed monthly" in monthly.visible_text
    assert "loading" not in monthly.visible_text


def test_status_and_headers_come_from_the_page_that_was_captured(
    site: LocalSite, browser: LaunchedBrowser
) -> None:
    # A wall answers 403, sets a cookie and moves on to the real page a moment later.
    site.add(
        "/gate",
        "<!doctype html><title>Gate</title><p>checking</p><script>"
        "document.cookie = 'pass=1; path=/';"
        "setTimeout(function () { location.replace('/open'); }, 200);</script>",
        status=403,
        headers={"X-Page": "gate"},
    )
    site.add("/open", "<!doctype html><title>Open</title><p>Prices</p>", headers={"X-Page": "open"})
    state = _rendered(
        render_states(browser.browser, site.url("/gate"), _single(), RenderSettings(), _no_pacing)[
            0
        ]
    )
    assert state.final_url == site.url("/open")
    assert state.status == 200
    assert state.headers["x-page"] == "open"
    assert "Prices" in state.visible_text


def test_an_action_that_opens_another_page_reports_that_page(
    site: LocalSite, browser: LaunchedBrowser
) -> None:
    site.add("/start", '<!doctype html><title>Start</title><a href="/missing">Details</a>')
    site.add("/missing", "<!doctype html><title>Gone</title><p>Page gone</p>", status=404)
    recipe = Recipe(
        method=Method.RENDER_INTERACT,
        states=[State(label="start"), State(label="details", actions=[ClickText(text="Details")])],
    )
    results = render_states(
        browser.browser, site.url("/start"), recipe, RenderSettings(), _no_pacing
    )
    start, details = (_rendered(result) for result in results)
    assert (start.status, start.final_url) == (200, site.url("/start"))
    assert details.final_url == site.url("/missing")
    assert details.status == 404
    assert "Page gone" in details.visible_text


def test_a_service_worker_does_not_answer_for_the_server(
    site: LocalSite, browser: LaunchedBrowser
) -> None:
    # The worker would answer /data itself. Blocked, the fetch reaches the server.
    site.add(
        "/with-worker",
        """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Worker</title></head>
<body><button id="check" type="button">Check</button><p id="out">idle</p>
<script>
navigator.serviceWorker.register("/worker.js").catch(function () {});
document.getElementById("check").addEventListener("click", function () {
  fetch("/data").then(function (r) { return r.text(); }).then(function (t) {
    document.getElementById("out").textContent = "answer: " + t;
  });
});
</script></body></html>""",
    )
    site.add(
        "/worker.js",
        """self.addEventListener("install", function () { self.skipWaiting(); });
self.addEventListener("activate", function (e) { e.waitUntil(self.clients.claim()); });
self.addEventListener("fetch", function (e) {
  if (new URL(e.request.url).pathname === "/data") e.respondWith(new Response("from the worker"));
});""",
        content_type="application/javascript",
    )
    site.add("/data", "from the server", content_type="text/plain")
    recipe = Recipe(
        method=Method.RENDER_INTERACT,
        states=[State(label="checked", actions=[ClickText(text="Check")])],
    )
    results = render_states(
        browser.browser, site.url("/with-worker"), recipe, RenderSettings(), _no_pacing
    )
    assert "answer: from the server" in _rendered(results[0]).visible_text
