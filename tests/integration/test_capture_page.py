"""Capturing a page end to end: robots, pacing, fetch or render, snapshot, status (Task 1.9)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2 as http
import pytest
from playwright.sync_api import Error as PlaywrightError

from mihenk.capture import run as run_module
from mihenk.capture.browser import LaunchedBrowser
from mihenk.capture.fetch import MAX_PAGE_BYTES, fetch_robots, make_client
from mihenk.capture.models import CaptureStatus, Method
from mihenk.capture.pace import Pace
from mihenk.capture.recipe import Recipe, State
from mihenk.capture.render import RenderedState, RenderSettings
from mihenk.capture.robots import RobotsFetch, RobotsGate
from mihenk.capture.run import CaptureResult, PageSpec, RunContext, capture_page
from mihenk.capture.snapshot import SnapshotRef
from tests.helpers.pages import load_expectations, page_names, serve_page
from tests.helpers.site import LocalSite

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
DISALLOW_ALL = "User-agent: *\nDisallow: /\n"


@pytest.fixture
def client() -> Iterator[http.Client]:
    with make_client("en") as running:
        yield running


def _ctx(
    tmp_path: Path,
    client: http.Client,
    *,
    browser: Any = None,
    pace: Pace | None = None,
) -> RunContext:
    return RunContext(
        run_id="run-1",
        snapshots_root=tmp_path,
        collection_country="NL",
        robots=RobotsGate(lambda url: fetch_robots(client, url)),
        pace=pace or Pace(0.0),
        http_client=client,
        browser=browser,
        render=RenderSettings(),
        now=lambda: NOW,
    )


def _spec(
    key: str,
    url: str,
    method: Method = Method.FETCH,
    *,
    states: list[State] | None = None,
    respect_robots: bool = True,
) -> PageSpec:
    recipe = Recipe(method=method, states=states or [State(label="default")])
    return PageSpec(key, url, recipe, respect_robots)


def _read(ref: SnapshotRef, name: str) -> str:
    return (ref.path / name).read_text(encoding="utf-8")


def _meta(ref: SnapshotRef) -> dict[str, Any]:
    meta: dict[str, Any] = json.loads(_read(ref, "meta.json"))
    return meta


def _only(results: list[CaptureResult]) -> CaptureResult:
    assert len(results) == 1, results
    return results[0]


def _snapshot(result: CaptureResult) -> SnapshotRef:
    assert result.snapshot is not None, result
    return result.snapshot


def _assert_files_match_the_hashes(ref: SnapshotRef) -> None:
    on_disk = {path.name for path in ref.path.iterdir()}
    assert on_disk == {*ref.files, "meta.json"}
    for name, digest in ref.files.items():
        assert hashlib.sha256((ref.path / name).read_bytes()).hexdigest() == digest, name
    meta = _meta(ref)
    assert meta["files"] == dict(ref.files)
    assert meta["html_sha256"] == ref.html_sha256 == ref.files["page.html"]
    assert meta["text_sha256"] == ref.text_sha256 == ref.files["text.txt"]
    assert meta["raw_sha256"] == ref.raw_sha256 == ref.files.get("page.raw")


def _assert_locale_matches(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    """Only the keys the expectation names. VAT phrases by containment: a phrase may also be
    reported under another language (a "+ IVA" is Spanish and Italian); the exact lists must
    match for the rest."""
    for key, wanted in expected.items():
        if key == "vat_phrases":
            for phrase in wanted:
                assert phrase in actual["vat_phrases"], (phrase, actual["vat_phrases"])
        else:
            assert actual[key] == wanted, key


# --- one page, one method -----------------------------------------------------------------


def test_static_table_by_fetch(site: LocalSite, tmp_path: Path, client: http.Client) -> None:
    url = serve_page(site, "static-table")
    result = _only(capture_page(_spec("static-table", url), _ctx(tmp_path, client)))
    assert result.status is CaptureStatus.OK
    assert result.method is Method.FETCH
    assert result.state_label == "default"
    ref = _snapshot(result)
    text = _read(ref, "text.txt")
    for expected in load_expectations("static-table")["fetch_text_contains"]:
        assert expected in text
    meta = _meta(ref)
    assert meta["method"] == "fetch"
    assert meta["url"] == meta["final_url"] == url
    assert meta["http_status"] == 200
    assert meta["collection_country"] == "NL"
    assert meta["captured_at"] == "2026-10-09T12:00:00Z"
    assert ref.path == tmp_path / "run-1" / "static-table" / "default"


def test_js_only_prices_are_missing_by_fetch(
    site: LocalSite, tmp_path: Path, client: http.Client
) -> None:
    url = serve_page(site, "js-only-prices")
    result = _only(capture_page(_spec("js-only-prices", url), _ctx(tmp_path, client)))
    assert result.status is CaptureStatus.OK
    text = _read(_snapshot(result), "text.txt")
    expect = load_expectations("js-only-prices")
    for expected in expect["fetch_text_contains"]:
        assert expected in text
    for missing in expect["fetch_text_lacks"]:
        assert missing not in text


@pytest.mark.browser
def test_js_only_prices_are_found_by_render(
    site: LocalSite, tmp_path: Path, client: http.Client, browser: LaunchedBrowser
) -> None:
    url = serve_page(site, "js-only-prices")
    ctx = _ctx(tmp_path, client, browser=browser.browser)
    result = _only(capture_page(_spec("js-only-prices", url, Method.RENDER), ctx))
    assert result.status is CaptureStatus.OK
    ref = _snapshot(result)
    text = _read(ref, "text.txt")
    for expected in load_expectations("js-only-prices")["render_text_contains"]:
        assert expected in text
    assert _meta(ref)["method"] == "render"
    assert (ref.path / "screenshot.png").read_bytes().startswith(b"\x89PNG")


@pytest.mark.browser
def test_billing_toggle_by_render_interact_gives_two_states(
    site: LocalSite, tmp_path: Path, client: http.Client, browser: LaunchedBrowser
) -> None:
    url = serve_page(site, "billing-toggle")
    states = load_expectations("billing-toggle")["states"]
    recipe = Recipe.model_validate(
        {
            "method": "render_interact",
            "states": [{"label": s["label"], "actions": s["actions"]} for s in states],
        }
    )
    ctx = _ctx(tmp_path, client, browser=browser.browser)
    results = capture_page(PageSpec("billing-toggle", url, recipe), ctx)
    assert [r.state_label for r in results] == ["annual", "monthly"]
    assert [r.status for r in results] == [CaptureStatus.OK, CaptureStatus.OK]
    folders = {_snapshot(r).path for r in results}
    assert folders == {
        tmp_path / "run-1" / "billing-toggle" / "annual",
        tmp_path / "run-1" / "billing-toggle" / "monthly",
    }
    for result in results:
        assert (_snapshot(result).path / "screenshot.png").is_file()
    assert "billed yearly" in _read(_snapshot(results[0]), "text.txt")
    assert "billed monthly" in _read(_snapshot(results[1]), "text.txt")


def test_bot_wall_by_fetch_is_needs_human_and_keeps_the_page(
    site: LocalSite, tmp_path: Path, client: http.Client
) -> None:
    url = serve_page(site, "bot-wall")
    result = _only(capture_page(_spec("bot-wall", url), _ctx(tmp_path, client)))
    assert result.status is CaptureStatus.NEEDS_HUMAN
    assert "person" in result.detail
    ref = _snapshot(result)  # kept as evidence
    assert _meta(ref)["http_status"] == 403
    assert "One moment, please" in _read(ref, "text.txt")


def test_a_page_under_disallow_is_blocked_and_never_requested(
    site: LocalSite, tmp_path: Path, client: http.Client
) -> None:
    site.add("/robots.txt", DISALLOW_ALL, content_type="text/plain")
    url = serve_page(site, "static-table")
    result = _only(capture_page(_spec("static-table", url), _ctx(tmp_path, client)))
    assert result.status is CaptureStatus.BLOCKED_BY_ROBOTS
    assert "disallowed" in result.detail
    assert result.snapshot is None
    assert "/robots.txt" in site.hits
    assert "/static-table" not in site.hits
    assert list(tmp_path.iterdir()) == []


def test_ignoring_robots_captures_the_disallowed_page(
    site: LocalSite, tmp_path: Path, client: http.Client
) -> None:
    site.add("/robots.txt", DISALLOW_ALL, content_type="text/plain")
    url = serve_page(site, "static-table")
    ctx = _ctx(tmp_path, client)
    result = _only(capture_page(_spec("static-table", url, respect_robots=False), ctx))
    assert result.status is CaptureStatus.OK
    assert result.snapshot is not None
    assert "/static-table" in site.hits
    assert "/robots.txt" not in site.hits


def test_a_site_spelled_two_ways_costs_one_robots_txt_fetch(
    site: LocalSite, tmp_path: Path, client: http.Client
) -> None:
    # capture_page checks the address as typed; the fetch hook checks the address as the http
    # client normalises it (lower-case scheme). Both are the same site.
    serve_page(site, "static-table")
    typed = site.url("/static-table").replace("http://", "HTTP://", 1)
    result = _only(capture_page(_spec("static-table", typed), _ctx(tmp_path, client)))
    assert result.status is CaptureStatus.OK
    assert site.hits.count("/robots.txt") == 1


def test_a_500_is_http_error_and_the_page_is_kept(
    site: LocalSite, tmp_path: Path, client: http.Client
) -> None:
    site.add("/boom", "<html><body><p>Something broke</p></body></html>", status=500)
    result = _only(capture_page(_spec("boom", site.url("/boom")), _ctx(tmp_path, client)))
    assert result.status is CaptureStatus.HTTP_ERROR
    assert "500" in result.detail
    ref = _snapshot(result)
    assert _meta(ref)["http_status"] == 500
    assert "Something broke" in _read(ref, "text.txt")


def test_a_failed_fetch_is_recorded_without_a_snapshot(
    site: LocalSite, tmp_path: Path, client: http.Client
) -> None:
    site.add("/slow", "<p>late</p>", delay_s=1.0)
    ctx = _ctx(tmp_path, client)
    with make_client("en", timeout_s=0.2) as short:
        ctx.http_client = short
        result = _only(capture_page(_spec("slow", site.url("/slow")), ctx))
    assert result.status is CaptureStatus.TIMEOUT
    assert result.snapshot is None


def test_render_without_a_browser_is_browser_unavailable_for_each_state(
    site: LocalSite, tmp_path: Path, client: http.Client
) -> None:
    url = serve_page(site, "billing-toggle")
    states = [State(label="annual"), State(label="monthly")]
    spec = _spec("billing-toggle", url, Method.RENDER_INTERACT, states=states)
    results = capture_page(spec, _ctx(tmp_path, client, browser=None))
    assert [(r.state_label, r.status) for r in results] == [
        ("annual", CaptureStatus.BROWSER_UNAVAILABLE),
        ("monthly", CaptureStatus.BROWSER_UNAVAILABLE),
    ]
    assert all(r.snapshot is None and r.method is Method.RENDER_INTERACT for r in results)
    assert "billing-toggle" not in site.hits


class _BrokenBrowser:
    """A browser that fails when a context is opened, as a crashed or disconnected one does."""

    def new_context(self, **_: object) -> object:
        raise PlaywrightError("Target page, context or browser has been closed\nCall log: ...")


def test_a_browser_error_out_of_render_is_browser_unavailable_for_each_state(
    site: LocalSite, tmp_path: Path, client: http.Client
) -> None:
    url = serve_page(site, "billing-toggle")
    states = [State(label="annual"), State(label="monthly")]
    spec = _spec("billing-toggle", url, Method.RENDER_INTERACT, states=states)
    results = capture_page(spec, _ctx(tmp_path, client, browser=_BrokenBrowser()))
    assert [(r.state_label, r.status) for r in results] == [
        ("annual", CaptureStatus.BROWSER_UNAVAILABLE),
        ("monthly", CaptureStatus.BROWSER_UNAVAILABLE),
    ]
    assert {r.detail for r in results} == {"Target page, context or browser has been closed"}
    assert all(r.snapshot is None for r in results)


def test_a_rendered_page_over_the_size_cap_is_too_large_and_not_kept(
    site: LocalSite,
    tmp_path: Path,
    client: http.Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # "€" is 3 bytes in UTF-8: fewer characters than the cap, more bytes than the cap.
    html = "<p>" + "€" * (MAX_PAGE_BYTES // 3 + 1) + "</p>"
    assert len(html) < MAX_PAGE_BYTES < len(html.encode("utf-8"))
    url = site.url("/huge")
    big = RenderedState("default", url, 200, {}, html, "text", b"\x89PNG")
    monkeypatch.setattr(run_module, "render_states", lambda *args, **kwargs: [big])
    ctx = _ctx(tmp_path, client, browser=object())
    result = _only(capture_page(_spec("huge", url, Method.RENDER), ctx))
    assert result.status is CaptureStatus.TOO_LARGE
    assert str(MAX_PAGE_BYTES) in result.detail
    assert result.snapshot is None
    assert list(tmp_path.iterdir()) == []


def test_huge_blob_is_ok_and_the_blob_is_marked_too_large(
    site: LocalSite, tmp_path: Path, client: http.Client
) -> None:
    url = serve_page(site, "huge-blob")
    result = _only(capture_page(_spec("huge-blob", url), _ctx(tmp_path, client)))
    assert result.status is CaptureStatus.OK
    blocks = json.loads(_read(_snapshot(result), "structured.json"))
    assert [(b["kind"], b["problem"]) for b in blocks] == [("json_script", "too_large")]


def test_windows_1254_page_keeps_its_turkish_text_and_locale(
    site: LocalSite, tmp_path: Path, client: http.Client
) -> None:
    url = serve_page(site, "windows-1254")
    result = _only(capture_page(_spec("windows-1254", url), _ctx(tmp_path, client)))
    assert result.status is CaptureStatus.OK
    ref = _snapshot(result)
    meta = _meta(ref)
    assert meta["encoding"] == "cp1254"
    assert "Aylık 199 TL" in _read(ref, "text.txt")
    assert {"language": "tr", "kind": "incl", "phrase": "KDV dahil"} in meta["locale"][
        "vat_phrases"
    ]
    assert meta["locale"]["html_lang"] == "tr"


# --- addresses that are not pages ---------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "ftp://127.0.0.1/pricing",
        "file:///C:/pricing.html",
        "javascript:alert(1)",
        "http://",
        "http:///pricing",
        "http://127.0.0.1:99999/pricing",
        "http://127.0.0.1:abc/pricing",
        "http://127.0.0.1:0/pricing",
        "http://[::1/pricing",
        "pricing",
        "",
    ],
)
def test_a_url_that_is_not_http_with_a_host_is_refused_without_a_request(
    tmp_path: Path, url: str
) -> None:
    requested: list[str] = []

    def record(request_url: str) -> RobotsFetch:
        requested.append(request_url)
        return RobotsFetch(404, b"", "fetched")

    ctx = RunContext(
        run_id="run-1",
        snapshots_root=tmp_path,
        collection_country="NL",
        robots=RobotsGate(record),
        pace=Pace(0.0),
        http_client=None,  # any use of it would raise
        browser=object(),
        render=RenderSettings(),
        now=lambda: NOW,
    )
    states = [State(label="annual"), State(label="monthly")]
    for method in (Method.FETCH, Method.RENDER_INTERACT):
        spec = _spec(
            "bad", url, method, states=states if method is Method.RENDER_INTERACT else None
        )
        results = capture_page(spec, ctx)
        assert len(results) == len(spec.recipe.states)
        for result in results:
            assert result.status is CaptureStatus.HTTP_ERROR
            assert result.detail.startswith("not a valid http(s) URL: ")
            assert result.snapshot is None
    assert requested == []
    assert list(tmp_path.iterdir()) == []


# --- redirects and robots.txt -------------------------------------------------------------


def test_a_redirect_to_a_disallowed_site_is_blocked_before_the_page_is_requested(
    tmp_path: Path, client: http.Client
) -> None:
    with LocalSite() as origin, LocalSite() as target:
        origin.redirect("/go", target.url("/page"))
        target.add("/robots.txt", DISALLOW_ALL, content_type="text/plain")
        target.add("/page", "<html><body><p>Starter €9 / month</p></body></html>")
        result = _only(capture_page(_spec("go", origin.url("/go")), _ctx(tmp_path, client)))
    assert result.status is CaptureStatus.BLOCKED_BY_ROBOTS
    assert result.detail.startswith(
        f"redirected to 127.0.0.1:{target.base_url.rsplit(':', 1)[1]}: "
    )
    assert "disallowed" in result.detail
    assert result.snapshot is None
    assert "/robots.txt" in target.hits
    assert "/page" not in target.hits
    assert list(tmp_path.iterdir()) == []


def test_a_redirect_to_a_disallowed_path_on_the_same_site_is_blocked(
    site: LocalSite, tmp_path: Path, client: http.Client
) -> None:
    site.add("/robots.txt", "User-agent: *\nDisallow: /private\n", content_type="text/plain")
    site.redirect("/go", "/private/pricing")
    site.add("/private/pricing", "<p>private</p>")
    result = _only(capture_page(_spec("go", site.url("/go")), _ctx(tmp_path, client)))
    assert result.status is CaptureStatus.BLOCKED_BY_ROBOTS
    assert result.detail.startswith("redirected to ")
    assert "/private/pricing" not in site.hits


def test_a_redirect_to_an_allowed_site_is_followed_and_both_sites_are_paced(
    tmp_path: Path, client: http.Client
) -> None:
    waits: list[str] = []

    class RecordingPace(Pace):
        def wait(self, host: str) -> float:
            waits.append(host)
            return 0.0

    with LocalSite() as origin, LocalSite() as target:
        origin.redirect("/go", target.url("/page"))
        target.add("/page", "<html><body><p>Starter €9 / month</p></body></html>")
        ctx = _ctx(tmp_path, client, pace=RecordingPace(0.0))
        result = _only(capture_page(_spec("go", origin.url("/go")), ctx))
    assert result.status is CaptureStatus.OK
    meta = _meta(_snapshot(result))
    assert meta["url"] == origin.url("/go")
    assert meta["final_url"] == target.url("/page")
    assert "/robots.txt" in target.hits  # the second site's rules were read before its page
    assert waits == [origin.base_url[len("http://") :], target.base_url[len("http://") :]]


@pytest.mark.browser
def test_render_that_ends_on_a_disallowed_site_keeps_no_snapshot(
    tmp_path: Path, client: http.Client, browser: LaunchedBrowser
) -> None:
    with LocalSite() as origin, LocalSite() as target:
        origin.redirect("/go", target.url("/page"))
        target.add("/robots.txt", DISALLOW_ALL, content_type="text/plain")
        target.add("/page", "<html><body><p>Starter €9 / month</p></body></html>")
        ctx = _ctx(tmp_path, client, browser=browser.browser)
        result = _only(capture_page(_spec("go", origin.url("/go"), Method.RENDER), ctx))
    assert result.status is CaptureStatus.BLOCKED_BY_ROBOTS
    assert "redirect" in result.detail
    assert "disallowed" in result.detail
    assert result.snapshot is None
    assert "/robots.txt" in target.hits
    assert list(tmp_path.iterdir()) == []


# --- the stage 1 "done" check -------------------------------------------------------------

_CASES = [
    pytest.param(
        name,
        method,
        id=f"{name}-{method}",
        marks=[] if method == "fetch" else [pytest.mark.browser],
    )
    for name in page_names()
    for method in load_expectations(name)["methods"]
]


@pytest.mark.parametrize(("name", "method"), _CASES)
def test_every_trap_page_by_its_methods(
    name: str,
    method: str,
    site: LocalSite,
    tmp_path: Path,
    client: http.Client,
    request: pytest.FixtureRequest,
) -> None:
    expect = load_expectations(name)
    url = serve_page(site, name)
    browser = None if method == "fetch" else request.getfixturevalue("browser").browser
    if method == "render_interact":
        expected_states = expect["states"]
        recipe = Recipe.model_validate(
            {
                "method": method,
                "states": [{"label": s["label"], "actions": s["actions"]} for s in expected_states],
            }
        )
    else:
        expected_states = [{"label": "default", "text_contains": [], "text_lacks": []}]
        recipe = Recipe(method=Method(method), states=[State(label="default")])

    results = capture_page(PageSpec(name, url, recipe), _ctx(tmp_path, client, browser=browser))

    assert [r.state_label for r in results] == [s["label"] for s in expected_states]
    for result, state in zip(results, expected_states, strict=True):
        assert result.status.value == expect["status"], result
        assert result.method.value == method
        ref = _snapshot(result)  # an ok page and a bot wall (kept as evidence) both have one
        _assert_files_match_the_hashes(ref)
        meta = _meta(ref)
        assert "locale" in meta
        text = _read(ref, "text.txt")
        if method == "fetch":
            _assert_locale_matches(meta["locale"], expect["locale"])
            for wanted in expect.get("fetch_text_contains", []):
                assert wanted in text
            for unwanted in expect.get("fetch_text_lacks", []):
                assert unwanted not in text
            assert (ref.path / "page.raw").is_file()
            assert not (ref.path / "screenshot.png").exists()
        else:
            assert (ref.path / "screenshot.png").is_file()
            assert not (ref.path / "page.raw").exists()
            wanted_texts = (
                state["text_contains"]
                if method == "render_interact"
                else expect.get("render_text_contains", [])
            )
            for wanted in wanted_texts:
                assert wanted in text
            if method == "render_interact":
                for unwanted in state["text_lacks"]:
                    assert unwanted not in text
        if "structured" in expect and method == "fetch":
            blocks = json.loads(_read(ref, "structured.json"))
            kinds = [(b["kind"], b["problem"]) for b in blocks]
            for wanted_block in expect["structured"]:
                assert (wanted_block["kind"], wanted_block["problem"]) in kinds
