from pathlib import Path

import pytest

from mihenk.capture.browser import LaunchedBrowser
from tests.helpers.site import LocalSite

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "pages"


@pytest.mark.browser
def test_drives_the_installed_browser_once(site: LocalSite, browser: LaunchedBrowser) -> None:
    site.add_file("/smoke", FIXTURES / "smoke" / "page.html")
    context = browser.browser.new_context(accept_downloads=False)
    try:
        page = context.new_page()
        page.goto(site.url("/smoke"))
        assert page.title() == "mihenk smoke page"
    finally:
        context.close()
    assert browser.channel in ("chrome", "msedge")


@pytest.mark.browser
def test_the_browser_gets_one_disable_features_and_one_host_rules_switch(
    browser: LaunchedBrowser,
) -> None:
    """The real command line, as the browser itself reports it (decision 0007).

    Chrome keeps only the last `--disable-features`, so `launch_browser` leaves out Playwright's
    own switch by its exact text and passes one merged switch. The day Playwright changes its
    list, its switch is no longer left out, two reach the browser, and this fails: copy the new
    list into `_PLAYWRIGHT_DISABLED_FEATURES` in `mihenk/capture/browser.py`.
    """
    context = browser.browser.new_context()
    try:
        page = context.new_page()
        page.goto("chrome://version")
        command_line = page.inner_text("#command_line", timeout=10_000)
    finally:
        context.close()
    assert command_line.count("--disable-features=") == 1
    features = command_line.split("--disable-features=")[1].split(" ")[0].split(",")
    assert "MediaRouter" in features  # Playwright's own
    assert "NetworkTimeServiceQuerying" in features  # mihenk's
    assert command_line.count("--host-resolver-rules=") == 1
    # The tests' confinement, in full, in the same switch as the services' rules.
    assert "MAP mtalk.google.com ~NOTFOUND" in command_line
    assert "MAP * ~NOTFOUND , EXCLUDE 127.0.0.1" in command_line
    assert "--proxy-server=http://127.0.0.1:9" in command_line
