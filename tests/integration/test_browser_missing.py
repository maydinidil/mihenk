from typing import Any

import pytest

from mihenk.capture import browser as browser_module
from mihenk.capture.browser import BrowserUnavailable, launch_browser


def test_a_missing_branded_browser_is_reported_as_unavailable(
    pw: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """launch_browser tells "not installed" from other failures by Playwright's wording.

    The wording is not documented API. This runs the real classifier against the real driver, so
    it fails loudly (a PlaywrightError escapes) the day Playwright changes the message.
    """
    monkeypatch.setattr(browser_module, "CHANNEL_ORDER", ("chrome-canary",))
    try:
        launched = launch_browser(pw)
    except BrowserUnavailable as exc:
        assert exc.tried == ("chrome-canary",)
    else:
        launched.browser.close()
        pytest.skip("Chrome Canary is installed here, so there is no missing-browser message")
