import pytest

from mihenk.capture.robots import MAX_ROBOTS_BYTES, RobotsFetch, RobotsGate, decide, robots_url

PAGE = "https://shop.example/pricing"
SHOP = "https://shop.example"


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


# A body longer than the limit: the last rule must not be read half-written.


def body_cut_inside_a_rule(
    rule: bytes, cut_after: int, tail: bytes = b"", eol: bytes = b"\n", before: bytes = b""
) -> bytes:
    """A robots.txt whose byte MAX_ROBOTS_BYTES falls `cut_after` bytes into `rule`.

    `before` is one more line, placed ahead of the padding."""
    head = b"User-agent: *" + eol + before
    padding = MAX_ROBOTS_BYTES - len(head) - len(eol) - cut_after
    body = head + b"#" * padding + eol + rule + tail
    assert body[:MAX_ROBOTS_BYTES].endswith(rule[:cut_after])
    assert len(body) > MAX_ROBOTS_BYTES
    return body


def test_a_rule_cut_by_the_size_limit_is_dropped_not_read_half_written() -> None:
    # Cut to `Disallow: /p`, the rule would block /public as well as /private.
    body = body_cut_inside_a_rule(b"Disallow: /private\n", len(b"Disallow: /p"), b"Allow: /\n")
    fetched = RobotsFetch(200, body, "fetched")
    assert decide(fetched, f"{SHOP}/public").allowed
    assert decide(fetched, f"{SHOP}/private").allowed  # past the limit, so never read


def test_the_rules_before_the_cut_still_apply() -> None:
    body = body_cut_inside_a_rule(b"Disallow: /private\n", 5, before=b"Disallow: /pricing\n")
    assert not decide(RobotsFetch(200, body, "fetched"), PAGE).allowed
    assert decide(RobotsFetch(200, body, "fetched"), f"{SHOP}/public").allowed


def test_a_cut_after_a_line_break_keeps_every_line() -> None:
    head = b"User-agent: *\nDisallow: /private\n"
    body = head + b"#" * (MAX_ROBOTS_BYTES - len(head) - 1) + b"\n" + b"x"
    assert len(body) == MAX_ROBOTS_BYTES + 1
    assert not decide(RobotsFetch(200, body, "fetched"), f"{SHOP}/private").allowed


def test_the_body_exactly_at_the_limit_is_used_whole() -> None:
    # No line break at the end: the last rule is complete, because the file ends there.
    rule = b"Disallow: /private"
    body = b"User-agent: *\n" + b"#" * (MAX_ROBOTS_BYTES - len(b"User-agent: *\n") - len(rule) - 1)
    body += b"\n" + rule
    assert len(body) == MAX_ROBOTS_BYTES
    assert not decide(RobotsFetch(200, body, "fetched"), f"{SHOP}/private").allowed
    # One byte more and the same rule is the half-written last line, which is dropped.
    longer = RobotsFetch(200, body + b"x", "fetched")
    assert decide(longer, f"{SHOP}/private").allowed


def test_a_bare_carriage_return_ends_a_line_too() -> None:
    body = body_cut_inside_a_rule(b"Disallow: /private\r", len(b"Disallow: /p"), eol=b"\r")
    assert decide(RobotsFetch(200, body, "fetched"), f"{SHOP}/public").allowed


def test_a_body_over_the_limit_without_a_line_break_is_read_as_empty() -> None:
    fetched = RobotsFetch(200, b"x" * (MAX_ROBOTS_BYTES + 1), "fetched")
    assert decide(fetched, PAGE).allowed


def test_a_2xx_without_a_body_is_unreadable_not_empty() -> None:
    for status in (200, 204, 299):
        decision = decide(RobotsFetch(status, None, "fetched"), PAGE)
        assert not decision.allowed
        assert decision.reason == "robots.txt body unreadable; treated as disallow-all"
    assert decide(RobotsFetch(200, b"", "fetched"), PAGE).allowed  # empty is not unreadable


@pytest.mark.parametrize(
    "url", ["http://shop.example:99999/", "http://[::1", "https://shop.example:-1/"]
)
def test_a_url_with_a_bad_port_or_address_is_disallowed_without_a_fetch(url: str) -> None:
    calls: list[str] = []

    def fetch(robots: str) -> RobotsFetch:
        calls.append(robots)
        return ok("User-agent: *\nAllow: /\n")

    decision = RobotsGate(fetch).check(url)
    assert decision.allowed is False
    assert decision.reason == "not a valid http(s) URL; treated as disallow-all"
    assert calls == []


# Today's behaviour, pinned. These are RFC 9309 rules that protego already follows.


def test_an_empty_robots_txt_allows_everything() -> None:
    assert decide(ok(""), PAGE).allowed
    assert decide(ok("\n\n# only a comment\n"), PAGE).allowed


def test_a_group_for_mihenk_wins_over_star_wherever_it_is_listed() -> None:
    star_first = "User-agent: *\nAllow: /\n\nUser-agent: mihenk\nDisallow: /pricing\n"
    star_last = "User-agent: mihenk\nAllow: /\n\nUser-agent: *\nDisallow: /pricing\n"
    assert not decide(ok(star_first), PAGE).allowed
    assert decide(ok(star_last), PAGE).allowed


def test_a_group_for_another_product_does_not_apply() -> None:
    assert decide(ok("User-agent: mihenkbot\nDisallow: /\n"), PAGE).allowed
    assert decide(ok("User-agent: notmihenk\nDisallow: /\n"), PAGE).allowed


def test_the_user_agent_token_is_matched_without_regard_to_case() -> None:
    assert not decide(ok("User-agent: MIHENK\nDisallow: /\n"), PAGE).allowed
    assert not decide(ok("User-agent: MiHeNk\nDisallow: /\n"), PAGE).allowed


def test_end_anchor_matches_the_end_of_the_path_and_query() -> None:
    text = "User-agent: *\nDisallow: /*.php$\n"
    assert not decide(ok(text), f"{SHOP}/x.php").allowed
    assert decide(ok(text), f"{SHOP}/x.php?a=1").allowed
    assert decide(ok(text), f"{SHOP}/x.phps").allowed


@pytest.mark.parametrize("status", [300, 301, 302, 304, 307, 308])
def test_a_redirect_status_reaching_decide_is_disallow_all(status: int) -> None:
    # fetch_robots follows redirects itself, so one that arrives here had no usable Location.
    decision = decide(RobotsFetch(status, b"", "fetched"), PAGE)
    assert not decision.allowed
    assert str(status) in decision.reason
