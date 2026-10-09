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
