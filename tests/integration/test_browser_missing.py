import pytest
from playwright.sync_api import Error as PlaywrightError


def test_missing_branded_browser_message_is_pinned(pw) -> None:  # type: ignore[no-untyped-def]
    """launch_browser tells "not installed" from other failures by Playwright's wording.

    The wording is not documented API, so this fails loudly the day Playwright changes it.
    """
    try:
        launched = pw.chromium.launch(channel="chrome-canary", headless=True)
    except PlaywrightError as exc:
        message = str(exc)
        assert "is not found at" in message or "Executable doesn't exist" in message
    else:
        launched.close()
        pytest.skip("Chrome Canary is installed here, so there is no missing-browser message")
