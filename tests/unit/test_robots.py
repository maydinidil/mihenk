import pytest

from mihenk.capture.robots import RobotsFetch, RobotsGate, decide, robots_url

PAGE = "https://shop.example/pricing"


def ok(text: str) -> RobotsFetch:
    return RobotsFetch(200, text.encode("utf-8"), "fetched")


def test_robots_url() -> None:
    assert robots_url("https://shop.example:8443/a/b?c=d") == "https://shop.example:8443/robots.txt"


def test_disallowed_path() -> None:
    decision = decide(ok("User-agent: *\nDisallow: /pricing\n"), PAGE)
    assert not decision.allowed
    assert "rules" in decision.reason


@pytest.mark.parametrize(
    "text", ["User-agent: *\nDisallow: /pricing\n", "User-agent: mihenk\nDisallow: /\n"]
)
def test_bom_does_not_hide_the_first_group(text: str) -> None:
    # Files saved by some Windows editors start with a UTF-8 byte order mark.
    with_bom = RobotsFetch(200, b"\xef\xbb\xbf" + text.encode("utf-8"), "fetched")
    assert not decide(with_bom, PAGE).allowed


def test_specific_group_beats_star() -> None:
    text = "User-agent: mihenk\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    assert not decide(ok(text), PAGE).allowed


def test_longest_match_wins() -> None:
    assert decide(ok("User-agent: *\nDisallow: /pri\nAllow: /pricing\n"), PAGE).allowed


def test_allow_wins_a_tie() -> None:
    assert decide(ok("User-agent: *\nDisallow: /pricing\nAllow: /pricing\n"), PAGE).allowed


def test_wildcard_and_end_anchor() -> None:
    text = "User-agent: *\nDisallow: /*.json$\n"
    assert not decide(ok(text), "https://shop.example/plans.json").allowed
    assert decide(ok(text), "https://shop.example/plans.jsonx").allowed


def test_html_soft_404_robots_allows() -> None:
    html = "<!doctype html><html><body><h1>Page not found</h1></body></html>"
    assert decide(ok(html), PAGE).allowed


@pytest.mark.parametrize("status", [404, 410, 400])
def test_missing_robots_allows(status: int) -> None:
    assert decide(RobotsFetch(status, b"", "fetched"), PAGE).allowed


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_refusals_and_errors_disallow(status: int) -> None:
    decision = decide(RobotsFetch(status, b"", "fetched"), PAGE)
    assert not decision.allowed
    assert str(status) in decision.reason


def test_unreachable_disallows() -> None:
    decision = decide(RobotsFetch(None, None, "unreachable: connection refused"), PAGE)
    assert not decision.allowed
    assert "unreachable" in decision.reason


def test_gate_fetches_once_per_site() -> None:
    calls: list[str] = []

    def fetch(url: str) -> RobotsFetch:
        calls.append(url)
        return ok("User-agent: *\nAllow: /\n")

    gate = RobotsGate(fetch)
    assert gate.check("https://shop.example/a").allowed
    assert gate.check("https://shop.example/b").allowed
    assert calls == ["https://shop.example/robots.txt"]


@pytest.mark.parametrize(
    ("page", "robots"),
    [
        ("HTTP://Shop.Example/x", "http://shop.example/robots.txt"),
        ("http://shop.example:80/x", "http://shop.example/robots.txt"),
        ("https://shop.example:443/x", "https://shop.example/robots.txt"),
        ("http://shop.example:443/x", "http://shop.example:443/robots.txt"),
        ("http://shop.example./x", "http://shop.example/robots.txt"),
        ("http://user:pw@shop.example/x", "http://shop.example/robots.txt"),
        ("http://user:pw@shop.example:8080/x?a=b#c", "http://shop.example:8080/robots.txt"),
        ("https://bücher.example/preise", "https://xn--bcher-kva.example/robots.txt"),
        ("http://[::1]:80/x", "http://[::1]/robots.txt"),
        ("http://[::1]:8080/x", "http://[::1]:8080/robots.txt"),
    ],
)
def test_robots_url_names_a_site_one_way(page: str, robots: str) -> None:
    assert robots_url(page) == robots


def test_one_site_spelled_two_ways_gets_one_robots_fetch() -> None:
    calls: list[str] = []

    def fetch(url: str) -> RobotsFetch:
        calls.append(url)
        return ok("User-agent: *\nAllow: /\n")

    gate = RobotsGate(fetch)
    assert gate.check("http://127.0.0.1:80/x").allowed  # as typed
    assert gate.check("http://127.0.0.1/x").allowed  # as the http client normalises it
    assert gate.check("HTTP://127.0.0.1/y").allowed
    assert calls == ["http://127.0.0.1/robots.txt"]


def test_the_robots_request_never_carries_the_user_name_or_password() -> None:
    calls: list[str] = []

    def fetch(url: str) -> RobotsFetch:
        calls.append(url)
        return ok("User-agent: *\nAllow: /\n")

    RobotsGate(fetch).check("http://user:secret@shop.example/pricing")
    assert calls == ["http://shop.example/robots.txt"]
