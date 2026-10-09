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


def test_second_request_to_the_same_site_waits_the_rest_of_the_interval() -> None:
    fake = FakeClock()
    pace = Pace(2.0, fake.clock, fake.sleep)
    pace.wait("a.example")
    fake.now += 0.5
    assert pace.wait("a.example") == 1.5


def test_different_sites_do_not_wait_for_each_other() -> None:
    fake = FakeClock()
    pace = Pace(2.0, fake.clock, fake.sleep)
    pace.wait("a.example")
    assert pace.wait("b.example") == 0.0


def test_host_key_ignores_case_and_path() -> None:
    assert host_key("https://Shop.Example:8443/x?y") == "shop.example:8443"
