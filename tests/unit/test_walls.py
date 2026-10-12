import pytest

from mihenk.capture.walls import looks_like_bot_wall
from tests.helpers.pages import PAGES_DIR


def _page(title: str = "Pricing", body: str = "<p>Starter €9 / month</p>") -> str:
    return f"<html><head><title>{title}</title></head><body>{body}</body></html>"


def test_the_bot_wall_trap_page_with_status_403_is_a_wall() -> None:
    html = (PAGES_DIR / "bot-wall" / "page.html").read_text(encoding="utf-8")
    assert looks_like_bot_wall(403, html)


def test_access_denied_title_with_status_403_is_a_wall() -> None:
    assert looks_like_bot_wall(403, _page(title="Access Denied"))


@pytest.mark.parametrize("status", [403, 429, 503])
@pytest.mark.parametrize(
    "title", ["Just a moment...", "Attention Required! | Site", "Please verify you are a human"]
)
def test_challenge_titles_are_walls_when_the_site_refuses(status: int, title: str) -> None:
    assert looks_like_bot_wall(status, _page(title=title))


@pytest.mark.parametrize("status", [200, 404, 500, None])
def test_challenge_titles_are_not_walls_without_a_refusing_status(status: int | None) -> None:
    # A blog post titled "Access Denied" or a render with no status is not a bot check.
    assert not looks_like_bot_wall(status, _page(title="Access Denied"))
    assert not looks_like_bot_wall(status, _page(title="Just a moment..."))


def test_a_normal_pricing_page_with_a_captcha_footer_link_is_not_a_wall() -> None:
    footer = '<footer><a href="/legal/captcha">About our captcha provider</a></footer>'
    assert not looks_like_bot_wall(200, _page(body="<p>Starter €9 / month</p>" + footer))


def test_cloudflare_challenge_script_with_status_403_is_a_wall() -> None:
    script = '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'
    assert looks_like_bot_wall(403, _page(title="Pricing", body=script))


def test_cloudflare_detection_script_on_an_ordinary_200_page_is_not_a_wall() -> None:
    # Cloudflare injects its JavaScript detections into pages it served without a challenge.
    script = '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'
    assert not looks_like_bot_wall(200, _page(body="<p>Starter €9 / month</p>" + script))


def test_imperva_resource_needs_a_refusing_status() -> None:
    script = '<script src="/_Incapsula_Resource?SWJIYLWA=1"></script>'
    assert looks_like_bot_wall(403, _page(body=script))
    assert not looks_like_bot_wall(200, _page(body="<p>Starter €9 / month</p>" + script))


@pytest.mark.parametrize(
    "marker",
    ["px-captcha", "captcha-delivery", "window._cf_chl_opt={", "Incapsula incident ID: 123"],
)
@pytest.mark.parametrize("status", [200, 403, None])
def test_vendor_challenge_markers_are_walls_at_any_status(status: int | None, marker: str) -> None:
    assert looks_like_bot_wall(status, _page(body=f"<div id='x'>{marker}</div>"))


TURNSTILE_INPUT = (
    '<input type="hidden" name="cf-turnstile-response" id="cf-chl-widget-abc_response">'
)


def test_a_turnstile_widget_on_an_ordinary_200_page_is_not_a_wall() -> None:
    # Cloudflare Turnstile puts this hidden input into the ordinary pages that have a form.
    form = f"<form action='/signup'>{TURNSTILE_INPUT}</form>"
    assert not looks_like_bot_wall(200, _page(body="<p>Starter €9 / month</p>" + form))
    assert not looks_like_bot_wall(None, _page(body="<p>Starter €9 / month</p>" + form))


def test_the_cloudflare_challenge_marker_with_status_403_is_a_wall() -> None:
    assert looks_like_bot_wall(403, _page(body=TURNSTILE_INPUT))
    assert looks_like_bot_wall(503, _page(body=TURNSTILE_INPUT))


def test_only_the_first_200000_characters_are_read() -> None:
    padding = "<p>plan</p>" * 30_000
    assert not looks_like_bot_wall(403, _page(body=padding + "px-captcha"))
    assert looks_like_bot_wall(200, _page(body="px-captcha" + padding))
