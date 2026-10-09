import pytest

from mihenk.capture.pace import Pace, host_key


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
