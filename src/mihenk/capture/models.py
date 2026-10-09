import re
from enum import StrEnum

# Run ids, page keys and state labels become folder names: lowercase, no separators.
# `\Z`, not `$`: `$` would also accept a trailing newline.
SAFE_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}\Z")


class Method(StrEnum):
    FETCH = "fetch"
    RENDER = "render"
    RENDER_INTERACT = "render_interact"


class CaptureStatus(StrEnum):
    OK = "ok"
    BLOCKED_BY_ROBOTS = "blocked_by_robots"
    HTTP_ERROR = "http_error"
    TIMEOUT = "timeout"
    NEEDS_HUMAN = "needs_human"
    TOO_LARGE = "too_large"
    BROWSER_UNAVAILABLE = "browser_unavailable"
    ACTION_FAILED = "action_failed"
