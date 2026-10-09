import pytest

from mihenk.capture.models import SAFE_SEGMENT, CaptureStatus, Method
from tests.helpers.pages import METHODS, STATUSES


def test_trap_page_methods_match_the_enum() -> None:
    assert {m.value for m in Method} == METHODS


def test_trap_page_statuses_match_the_enum() -> None:
    assert {s.value for s in CaptureStatus} == STATUSES


def test_values_are_the_lowercase_names() -> None:
    assert all(s.value == s.name.lower() for s in CaptureStatus)
    assert all(m.value == m.name.lower() for m in Method)


@pytest.mark.parametrize("segment", ["a", "0", "run-1", "run_2026_10_09", "a" * 64, "9-9", "x_-"])
def test_safe_segment_accepts(segment: str) -> None:
    assert SAFE_SEGMENT.match(segment)


@pytest.mark.parametrize(
    "segment",
    [
        "",
        "a" * 65,
        "-a",
        "_a",
        "Run",
        "a b",
        "a/b",
        "a\b",
        "..",
        "a.b",
        "a\n",
        "\na",
        "ü",
        "ı",
        "a:b",
    ],
)
def test_safe_segment_rejects(segment: str) -> None:
    assert SAFE_SEGMENT.match(segment) is None
    assert SAFE_SEGMENT.fullmatch(segment) is None
