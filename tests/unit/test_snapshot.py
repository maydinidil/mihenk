import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mihenk.capture.locale import LocaleMarkers
from mihenk.capture.models import Method
from mihenk.capture.snapshot import (
    MAX_PATH_CHARS,
    SnapshotExists,
    SnapshotInput,
    new_run_id,
    write_snapshot,
)

NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
NO_MARKERS = LocaleMarkers(None, None, (), (), ())
RUN_ID = "20261008t120000z-abc123"


def snap(run_id: str = RUN_ID, **changes: object) -> SnapshotInput:
    base = dict(
        run_id=run_id,
        page_key="acme-pricing",
        state_label="default",
        url="https://acme.example/p",
        final_url="https://acme.example/p",
        http_status=200,
        method=Method.FETCH,
        captured_at=NOW,
        html="<p>Aylık 199 TL</p>",
        raw_bytes="<p>Aylık 199 TL</p>".encode("cp1254"),
        encoding="cp1254",
        text="Aylık 199 TL\n",
        structured=[],
        screenshot_png=None,
        locale=NO_MARKERS,
        collection_country="NL",
    )
    base.update(changes)
    return SnapshotInput(**base)  # type: ignore[arg-type]


def test_run_ids_are_safe_and_sortable() -> None:
    run_id = new_run_id(NOW)
    assert run_id.startswith("20261008t120000z-")
    assert run_id == run_id.lower()


def test_hashes_match_the_files(tmp_path: Path) -> None:
    ref = write_snapshot(tmp_path, snap())
    assert hashlib.sha256((ref.path / "page.html").read_bytes()).hexdigest() == ref.html_sha256
    assert hashlib.sha256((ref.path / "text.txt").read_bytes()).hexdigest() == ref.text_sha256
    assert hashlib.sha256((ref.path / "page.raw").read_bytes()).hexdigest() == ref.raw_sha256
    meta = json.loads((ref.path / "meta.json").read_text("utf-8"))
    assert meta["captured_at"] == "2026-10-08T12:00:00Z"
    assert meta["collection_country"] == "NL"


def test_turkish_text_survives_snapshot(tmp_path: Path) -> None:
    ref = write_snapshot(tmp_path, snap(text="Aylık 199 TL, KDV DAHİL, İstanbul şube\n"))
    assert (
        ref.path / "text.txt"
    ).read_bytes() == "Aylık 199 TL, KDV DAHİL, İstanbul şube\n".encode()


def test_snapshots_are_never_overwritten(tmp_path: Path) -> None:
    write_snapshot(tmp_path, snap())
    with pytest.raises(SnapshotExists):
        write_snapshot(tmp_path, snap())


@pytest.mark.parametrize("bad", ["../escape", "Upper", "a/b", "", "x" * 65])
def test_unsafe_path_segments_are_refused(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError, match="unsafe"):
        write_snapshot(tmp_path, snap(page_key=bad))


def test_naive_time_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="UTC"):
        write_snapshot(tmp_path, snap(captured_at=datetime(2026, 10, 8, 12, 0, 0)))  # noqa: DTZ001


def test_snapshot_in_path_with_spaces_and_turkish_letters(tmp_path: Path) -> None:
    root = tmp_path / "Ayşe Yılmaz" / "mihenk data" / "snapshots"
    ref = write_snapshot(root, snap())
    assert (ref.path / "meta.json").is_file()


def test_no_temporary_folder_is_left_after_a_failure(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        write_snapshot(tmp_path, snap(screenshot_png=object()))
    run_folder = tmp_path / "20261008t120000z-abc123" / "acme-pricing"
    assert not any(p.name.startswith(".tmp-") for p in run_folder.iterdir())


def longest_path(root: Path, page_key: str, state_label: str) -> int:
    """The longest path a snapshot writes: the temporary sibling's file or the final one."""
    temporary = root / RUN_ID / page_key / (".tmp-" + "x" * 8) / "structured.json"
    final = root / RUN_ID / page_key / state_label / "structured.json"
    return max(len(str(temporary)), len(str(final)))


def padded_root(tmp_path: Path, page_key: str, state_label: str, length: int) -> Path:
    """A root (not created) under tmp_path whose longest snapshot path has `length` characters,
    or, when tmp_path alone is already longer than that, one pad letter more than tmp_path."""
    pad = max(1, 1 + length - longest_path(tmp_path / "p", page_key, state_label))
    return tmp_path / ("p" * pad)


def test_path_over_the_windows_limit_is_refused_before_anything_is_created(
    tmp_path: Path,
) -> None:
    page_key, state_label = "k" * 64, "s" * 64
    root = padded_root(tmp_path, page_key, state_label, MAX_PATH_CHARS + 1)
    longest = longest_path(root, page_key, state_label)
    assert longest > MAX_PATH_CHARS
    with pytest.raises(ValueError, match="too long") as refused:
        write_snapshot(root, snap(page_key=page_key, state_label=state_label))
    assert str(longest) in str(refused.value)
    assert str(MAX_PATH_CHARS) in str(refused.value)
    assert not root.exists()


@pytest.mark.parametrize(
    "state_label", ["s" * 32, "a"], ids=["final-is-longer", "temporary-is-longer"]
)
def test_the_limit_is_exact_at_the_longest_path(tmp_path: Path, state_label: str) -> None:
    page_key = "k" * 32
    just_under = padded_root(tmp_path, page_key, state_label, MAX_PATH_CHARS)
    if longest_path(just_under, page_key, state_label) != MAX_PATH_CHARS:
        pytest.skip("the temporary folder is already too long to build a root of this size")
    ref = write_snapshot(just_under, snap(page_key=page_key, state_label=state_label))
    assert (ref.path / "structured.json").is_file()

    one_over = padded_root(tmp_path, page_key, state_label, MAX_PATH_CHARS + 1)
    assert longest_path(one_over, page_key, state_label) == MAX_PATH_CHARS + 1
    with pytest.raises(ValueError, match="too long"):
        write_snapshot(one_over, snap(page_key=page_key, state_label=state_label))
    assert not one_over.exists()
