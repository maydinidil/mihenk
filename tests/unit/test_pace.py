import pytest

from mihenk.capture.fetch import make_client
from mihenk.capture.pace import Pace, host_key, idna_host


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_first_request_does_not_wait() -> None:
    fake = FakeClock()
    assert Pace(2.0, fake.clock, fake.sleep).wait("a.example") == 0.0
    assert fake.slept == []


def test_second_request_to_the_same_site_waits_the_rest_of_the_interval() -> None:
    fake = FakeClock()
    pace = Pace(2.0, fake.clock, fake.sleep)
    pace.wait("a.example")
    fake.now += 0.5
    assert pace.wait("a.example") == 1.5
    assert fake.slept == [1.5]


def test_different_sites_do_not_wait_for_each_other() -> None:
    fake = FakeClock()
    pace = Pace(2.0, fake.clock, fake.sleep)
    pace.wait("a.example")
    assert pace.wait("b.example") == 0.0
    assert fake.slept == []


def test_host_key_ignores_case_and_path() -> None:
    assert host_key("https://Shop.Example:8443/x?y") == "shop.example:8443"


@pytest.mark.parametrize(
    "url",
    [
        "https://shop.example/p",
        "https://shop.example:443/p",
        "http://shop.example:80/p",
        "https://user:pw@shop.example/p",
        "https://shop.example./p",
        "https://shop.example:/p",
        "https://SHOP.example/p",
    ],
)
def test_one_site_has_one_key_however_it_is_spelled(url: str) -> None:
    # Otherwise each spelling gets its own pacing slot and two requests go out back to back.
    assert host_key(url) == "shop.example"


def test_host_key_never_holds_credentials() -> None:
    assert "pw" not in host_key("https://user:pw@shop.example:8443/p")


def test_unicode_and_punycode_hosts_share_a_key() -> None:
    assert host_key("https://bücher.example/p") == host_key("https://xn--bcher-kva.example/p")
    assert host_key("https://bücher.example/p") == "xn--bcher-kva.example"


def test_ipv6_host_keeps_its_brackets_with_a_port() -> None:
    assert host_key("http://[::1]:8080/p") == "[::1]:8080"


def test_a_clock_that_steps_back_never_makes_the_wait_longer_than_one_interval() -> None:
    fake = FakeClock()
    pace = Pace(2.0, fake.clock, fake.sleep)
    pace.wait("a.example")
    fake.now -= 10.0  # the clock steps back ten seconds
    assert pace.wait("a.example") == 2.0
    assert fake.slept == [2.0]
    # The slot restarts from the new time, so the next request waits one interval again, not more.
    assert pace.wait("a.example") == 2.0
    assert fake.slept == [2.0, 2.0]


def test_a_wait_that_is_already_over_stays_zero_after_the_clock_steps_forward() -> None:
    fake = FakeClock()
    pace = Pace(2.0, fake.clock, fake.sleep)
    pace.wait("a.example")
    fake.now += 3600.0
    assert pace.wait("a.example") == 0.0
    assert fake.slept == []


# --- international host names: spelled as the client spells them -------------------------------


def _clients_host(url: str) -> str:
    """The host the http client sends the request to: its Host header (the port only when it is
    not the scheme's default, as `host_key` writes it)."""
    with make_client("en") as client:
        request = client.build_request("GET", url)
    host = request.url.raw_host.decode("ascii")
    assert request.headers["host"].split(":")[0] == host
    return request.headers["host"]


@pytest.mark.parametrize(
    ("url", "key"),
    [
        ("http://fa\u00df.de/", "xn--fa-hia.de"),  # sharp s: IDNA 2003 would read it as "ss"
        ("http://\u03c3\u03b1\u03c2.gr/", "xn--mxa8ab.gr"),  # final sigma: 2003 maps it to sigma
        ("http://\u03bf\u03b4\u03c5\u03c3\u03c3\u03b5\u03cd\u03c2.gr/", "xn--pxac2aodam1e.gr"),
        ("https://b\u00fccher.example/preise", "xn--bcher-kva.example"),
        ("http://FA\u00df.DE:80/preise", "xn--fa-hia.de"),
        ("http://fa\u00df.de:8080/preise", "xn--fa-hia.de:8080"),
    ],
)
def test_host_key_spells_an_international_host_as_the_client_does(url: str, key: str) -> None:
    assert host_key(url) == key
    assert host_key(url) == _clients_host(url)


def test_an_international_host_does_not_become_another_site() -> None:
    # "fass.de" is another domain than "fa\u00df.de" (xn--fa-hia.de).
    assert host_key("http://fa\u00df.de/") != host_key("http://fass.de/")
    assert host_key("http://fa\u00df.de/") == host_key("http://xn--fa-hia.de/")


def test_idna_host_keeps_the_old_spelling_for_a_url_the_client_refuses() -> None:
    # A zero-width joiner between two ordinary letters is not valid IDNA 2008: the client
    # refuses the address, and the host is then spelled by Python's codec, which drops it.
    assert idna_host("http://a\u200db.de/") == "ab.de"


@pytest.mark.parametrize(
    ("url", "host"),
    [
        ("http://Shop.Example./x", "shop.example"),
        ("http://127.0.0.1:5000/x", "127.0.0.1"),
        ("http://[::1]:80/x", "[::1]"),
        ("http://user:pw@shop.example:80/x", "shop.example"),
    ],
)
def test_idna_host_still_strips_the_dot_the_port_and_the_credentials(url: str, host: str) -> None:
    assert idna_host(url) == host


# --- a request the browser made is marked, not waited for --------------------------------------


def test_mark_records_a_request_without_sleeping() -> None:
    fake = FakeClock()
    pace = Pace(2.0, fake.clock, fake.sleep)
    pace.mark("a.example")
    assert fake.slept == []
    assert pace.wait("a.example") == 2.0  # a full interval after the mark
    assert fake.slept == [2.0]


def test_mark_counts_from_now_and_leaves_other_sites_alone() -> None:
    fake = FakeClock()
    pace = Pace(2.0, fake.clock, fake.sleep)
    pace.wait("a.example")
    fake.now += 5.0
    pace.mark("a.example")
    fake.now += 0.5
    assert pace.wait("a.example") == 1.5
    assert pace.wait("b.example") == 0.0
