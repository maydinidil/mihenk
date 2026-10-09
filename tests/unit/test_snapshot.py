import errno
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mihenk.capture import snapshot as snapshot_module
from mihenk.capture.locale import LocaleMarkers
from mihenk.capture.models import SAFE_SEGMENT, Method
from mihenk.capture.snapshot import (
    MAX_PATH_CHARS,
    SnapshotExists,
    SnapshotInput,
    new_run_id,
    write_snapshot,
)
from mihenk.trim.structured import StructuredBlock, StructuredKind, extract_structured

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


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_meta(folder: Path) -> dict[str, object]:
    meta: dict[str, object] = json.loads((folder / "meta.json").read_text("utf-8"))
    return meta


def test_meta_repeats_the_refs_hashes_and_lists_every_file(tmp_path: Path) -> None:
    ref = write_snapshot(tmp_path, snap(screenshot_png=b"\x89PNG not really a picture"))
    meta = read_meta(ref.path)
    assert meta["html_sha256"] == ref.html_sha256
    assert meta["text_sha256"] == ref.text_sha256
    assert meta["raw_sha256"] == ref.raw_sha256
    assert meta["files"] == ref.files
    assert ref.files == {
        path.name: sha256_of(path) for path in ref.path.iterdir() if path.name != "meta.json"
    }


def test_without_raw_bytes_there_is_no_raw_file_and_no_raw_hash(tmp_path: Path) -> None:
    ref = write_snapshot(tmp_path, snap(raw_bytes=None, encoding=None))
    assert not (ref.path / "page.raw").exists()
    assert ref.raw_sha256 is None
    assert read_meta(ref.path)["raw_sha256"] is None
    assert "page.raw" not in ref.files
    assert "page.raw" not in read_meta(ref.path)["files"]  # type: ignore[operator]


def test_a_screenshot_is_written_and_hashed(tmp_path: Path) -> None:
    picture = b"\x89PNG\r\n\x1a\n and some more bytes"
    ref = write_snapshot(tmp_path, snap(screenshot_png=picture))
    assert (ref.path / "screenshot.png").read_bytes() == picture
    assert ref.files["screenshot.png"] == hashlib.sha256(picture).hexdigest()


def test_the_folder_holds_exactly_the_listed_files_and_meta(tmp_path: Path) -> None:
    for changes in ({}, {"raw_bytes": None}, {"screenshot_png": b"png"}):
        ref = write_snapshot(tmp_path, snap(run_id=new_run_id(NOW), **changes))
        assert {path.name for path in ref.path.iterdir()} == {*ref.files, "meta.json"}
        assert {"page.html", "text.txt", "structured.json"} <= set(ref.files)


def test_json_files_have_no_windows_line_endings(tmp_path: Path) -> None:
    block = StructuredBlock(StructuredKind.JSONLD, 0, None, None, 20, {"a": [1, 2], "b": "İ"}, None)
    ref = write_snapshot(tmp_path, snap(structured=[block]))
    for name in ("meta.json", "structured.json"):
        data = (ref.path / name).read_bytes()
        assert b"\r" not in data
        assert b"\n" in data
    assert ref.files["structured.json"] == sha256_of(ref.path / "structured.json")


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
    assert not (run_folder / "default").exists()  # the folder it was to become never appeared


def utf16_units(path: Path) -> int:
    """The length Windows counts: UTF-16 code units, so an emoji counts twice."""
    return len(str(path).encode("utf-16-le")) // 2


def longest_path(root: Path, page_key: str, state_label: str) -> int:
    """The longest path a snapshot writes: the temporary sibling's file (`.tmp-` and 16 hex
    characters) or the final one."""
    temporary = root / RUN_ID / page_key / (".tmp-" + "x" * 16) / "structured.json"
    final = root / RUN_ID / page_key / state_label / "structured.json"
    return max(utf16_units(temporary), utf16_units(final))


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


# --- the basics that had no test ----------------------------------------------------------------


def test_run_ids_match_the_safe_segment_rule_and_differ_between_calls() -> None:
    first, second = new_run_id(NOW), new_run_id(NOW)
    assert SAFE_SEGMENT.fullmatch(first)
    assert SAFE_SEGMENT.fullmatch(second)
    assert first != second


def test_a_second_write_with_other_content_is_refused_and_changes_nothing(tmp_path: Path) -> None:
    first = write_snapshot(tmp_path, snap())
    before = {path.name: path.read_bytes() for path in first.path.iterdir()}
    other = snap(html="<p>other</p>", text="other\n", raw_bytes=b"other", url="https://b.example/")
    with pytest.raises(SnapshotExists):
        write_snapshot(tmp_path, other)
    assert {path.name: path.read_bytes() for path in first.path.iterdir()} == before
    assert [p.name for p in first.path.parent.iterdir()] == [first.path.name]  # no temporary left


# --- lone surrogates ----------------------------------------------------------------------------

LONE = chr(0xD83D)
FFFD = "\N{REPLACEMENT CHARACTER}"


def jsonld_block_with(**fields: object) -> StructuredBlock:
    base: dict[str, object] = dict(
        kind=StructuredKind.JSONLD,
        index=0,
        script_id=None,
        raw=None,
        size_bytes=9,
        parsed=None,
        problem="invalid_json: unpaired surrogate",
    )
    base.update(fields)
    return StructuredBlock(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "file"),
    [
        ({"html": f"<p>price {LONE} 9</p>"}, "page.html"),
        ({"text": f"price {LONE} 9\n"}, "text.txt"),
        ({"url": f"https://acme.example/{LONE}"}, "meta.json"),
        ({"final_url": f"https://acme.example/{LONE}"}, "meta.json"),
        (
            {"locale": LocaleMarkers(f"en{LONE}", f"nl{LONE}", (LONE,), (), ())},
            "meta.json",
        ),
        ({"structured": [jsonld_block_with(raw='{"price": "' + LONE + '"}')]}, "structured.json"),
        ({"structured": [jsonld_block_with(script_id=f"id{LONE}")]}, "structured.json"),
    ],
    ids=["html", "text", "url", "final_url", "locale", "structured-raw", "structured-id"],
)
def test_a_lone_surrogate_is_replaced_instead_of_losing_the_capture(
    tmp_path: Path, changes: dict[str, object], file: str
) -> None:
    ref = write_snapshot(tmp_path, snap(**changes))
    data = (ref.path / file).read_bytes()
    text = data.decode("utf-8")  # strict: it must be valid UTF-8
    assert FFFD in text
    assert LONE not in text
    for path in ref.path.iterdir():
        if path.suffix in {".html", ".txt", ".json"}:
            path.read_bytes().decode("utf-8")  # every text file of the snapshot is valid UTF-8
    # The hashes are over the bytes that were written.
    if file != "meta.json":
        assert ref.files[file] == hashlib.sha256(data).hexdigest()
    else:
        assert read_meta(ref.path)["files"] == ref.files


def test_the_replacement_lands_in_the_field_it_came_from(tmp_path: Path) -> None:
    ref = write_snapshot(
        tmp_path,
        snap(
            url=f"https://acme.example/a{LONE}b",
            final_url=f"https://acme.example/c{LONE}d",
            locale=LocaleMarkers(f"e{LONE}n", None, (), (), ()),
        ),
    )
    meta = read_meta(ref.path)
    assert meta["url"] == f"https://acme.example/a{FFFD}b"
    assert meta["final_url"] == f"https://acme.example/c{FFFD}d"
    assert meta["locale"]["html_lang"] == f"e{FFFD}n"  # type: ignore[index]


def test_text_without_surrogates_is_written_byte_for_byte(tmp_path: Path) -> None:
    emoji = chr(0x1F600)
    ref = write_snapshot(tmp_path, snap(html=f"<p>{emoji} İstanbul €9</p>", text=f"{emoji}\n"))
    assert (ref.path / "page.html").read_bytes() == f"<p>{emoji} İstanbul €9</p>".encode()
    assert (ref.path / "text.txt").read_bytes() == f"{emoji}\n".encode()


# --- depth ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("levels", [511, 512])
def test_a_block_at_the_depth_cap_is_written_without_a_recursion_error(
    tmp_path: Path, levels: int
) -> None:
    body = "[" * levels + "]" * levels
    (block,) = extract_structured(f'<script type="application/ld+json">{body}</script>')
    assert block.problem is None  # it passed the cap, so the dump below has to cope with it
    ref = write_snapshot(tmp_path, snap(structured=[block]))
    dumped = json.loads((ref.path / "structured.json").read_text("utf-8"))
    assert dumped[0]["parsed"] == block.parsed


# --- durability ---------------------------------------------------------------------------------


class Events:
    """What the snapshot asked the operating system to do, in order."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, folders_can_be_synced: bool) -> None:
        self.log: list[tuple[str, str]] = []
        self.opened_folders: list[Path] = []
        real_fsync, real_open, real_close, real_rename = os.fsync, os.open, os.close, os.rename
        folder_fd = 987_654  # a descriptor number nothing else holds

        def fsync(fd: int) -> None:
            if fd == folder_fd:
                self.log.append(("fsync-folder", ""))
                return
            self.log.append(("fsync-file", ""))
            real_fsync(fd)

        def open_(path: str | os.PathLike[str], flags: int, *args: int) -> int:
            if Path(path).is_dir():
                self.opened_folders.append(Path(path))
                self.log.append(("open-folder", Path(path).name))
                return folder_fd
            return real_open(path, flags, *args)

        def close(fd: int) -> None:
            if fd == folder_fd:
                self.log.append(("close-folder", ""))
                return
            real_close(fd)

        def rename(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
            if Path(src).name.startswith(".tmp-"):
                self.log.append(("rename", ""))
            real_rename(src, dst)

        monkeypatch.setattr(snapshot_module, "_CAN_SYNC_FOLDERS", folders_can_be_synced)
        monkeypatch.setattr(os, "fsync", fsync)
        monkeypatch.setattr(os, "open", open_)
        monkeypatch.setattr(os, "close", close)
        monkeypatch.setattr(os, "rename", rename)

    def names(self) -> list[str]:
        return [name for name, _ in self.log]


def test_every_file_is_flushed_to_the_disk_before_the_folder_is_renamed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = Events(monkeypatch, folders_can_be_synced=False)
    ref = write_snapshot(tmp_path, snap(screenshot_png=b"png"))
    files = len(ref.files) + 1  # and meta.json
    assert events.names() == ["fsync-file"] * files + ["rename"]


def test_on_posix_the_new_folder_and_its_parent_are_flushed_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = Events(monkeypatch, folders_can_be_synced=True)
    ref = write_snapshot(tmp_path, snap())
    files = len(ref.files) + 1
    assert events.names() == [
        *["fsync-file"] * files,
        # the entries of the temporary folder, then the rename, then the folder that holds the name
        *["open-folder", "fsync-folder", "close-folder"],
        "rename",
        *["open-folder", "fsync-folder", "close-folder"],
    ]
    assert events.opened_folders[-1] == ref.path.parent


def test_a_folder_that_cannot_be_flushed_does_not_fail_the_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(snapshot_module, "_CAN_SYNC_FOLDERS", True)
    real_open, real_fsync, real_close = os.open, os.fsync, os.close

    def refuse(path: str | os.PathLike[str], flags: int, *args: int) -> int:
        if Path(path).is_dir():
            raise PermissionError(errno.EACCES, "cannot open a folder here")
        return real_open(path, flags, *args)

    monkeypatch.setattr(os, "open", refuse)
    assert (write_snapshot(tmp_path, snap()).path / "meta.json").is_file()

    folder_fd = 987_654

    def open_folder(path: str | os.PathLike[str], flags: int, *args: int) -> int:
        return folder_fd if Path(path).is_dir() else real_open(path, flags, *args)

    def fsync(fd: int) -> None:
        if fd == folder_fd:
            raise OSError(errno.EINVAL, "this file system cannot flush a folder")
        real_fsync(fd)

    def close(fd: int) -> None:
        if fd != folder_fd:
            real_close(fd)

    monkeypatch.setattr(os, "open", open_folder)
    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "close", close)
    ref = write_snapshot(tmp_path, snap(run_id="20261008t120000z-def456"))
    assert (ref.path / "meta.json").is_file()


def test_folders_are_flushed_everywhere_but_windows() -> None:
    assert (os.name != "nt") == snapshot_module._CAN_SYNC_FOLDERS


# --- the rename ---------------------------------------------------------------------------------

Outcome = Exception | Callable[[Path, Path], None] | None


def scripted_rename(monkeypatch: pytest.MonkeyPatch, outcomes: list[Outcome]) -> list[Path]:
    """The snapshot's rename follows `outcomes` one attempt at a time (None: really rename);
    renames of anything else pass through. Returns the temporary folder of each attempt."""
    real_rename = os.rename
    attempts: list[Path] = []

    def rename(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        if not Path(src).name.startswith(".tmp-"):
            real_rename(src, dst)
            return
        attempts.append(Path(src))
        outcome = outcomes[len(attempts) - 1] if len(attempts) <= len(outcomes) else None
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is not None:
            outcome(Path(src), Path(dst))
            return
        real_rename(src, dst)

    monkeypatch.setattr(os, "rename", rename)
    return attempts


@pytest.fixture
def pauses(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """The pauses between rename attempts, recorded and skipped."""
    recorded: list[float] = []
    monkeypatch.setattr(snapshot_module.time, "sleep", recorded.append)
    return recorded


def denied() -> PermissionError:
    return PermissionError(errno.EACCES, "the file is held by another process")


def test_a_rename_held_up_for_a_moment_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pauses: list[float]
) -> None:
    attempts = scripted_rename(monkeypatch, [denied(), denied()])
    ref = write_snapshot(tmp_path, snap())
    assert len(attempts) == 3
    assert pauses == [0.1, 0.1]
    assert (ref.path / "meta.json").is_file()
    assert [p.name for p in ref.path.parent.iterdir()] == [ref.path.name]


def test_a_rename_that_never_succeeds_is_retried_five_times_and_then_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pauses: list[float]
) -> None:
    attempts = scripted_rename(monkeypatch, [denied()] * 9)
    with pytest.raises(PermissionError):
        write_snapshot(tmp_path, snap())
    assert len(attempts) == 6  # the first attempt and five retries
    assert pauses == [0.1] * 5  # before each retry, not after the last failure
    run_folder = tmp_path / RUN_ID / "acme-pricing"
    assert list(run_folder.iterdir()) == []  # no snapshot, and the temporary folder is gone


def test_a_rename_that_works_on_the_last_retry_still_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pauses: list[float]
) -> None:
    attempts = scripted_rename(monkeypatch, [denied()] * 5)
    assert (write_snapshot(tmp_path, snap()).path / "meta.json").is_file()
    assert len(attempts) == 6
    assert pauses == [0.1] * 5


def appears_then_denied(src: Path, dst: Path) -> None:
    """Another writer publishes the same snapshot just before this rename; Windows says denied."""
    dst.mkdir()
    (dst / "other-writers-file").write_bytes(b"theirs")
    raise denied()


def test_a_target_that_appears_during_the_write_is_snapshot_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pauses: list[float]
) -> None:
    attempts = scripted_rename(monkeypatch, [appears_then_denied])
    with pytest.raises(SnapshotExists):
        write_snapshot(tmp_path, snap())
    assert len(attempts) == 1  # a snapshot that exists is not retried
    assert pauses == []
    target = tmp_path / RUN_ID / "acme-pricing" / "default"
    assert (target / "other-writers-file").read_bytes() == b"theirs"  # theirs, untouched
    assert [p.name for p in target.parent.iterdir()] == ["default"]


@pytest.mark.parametrize(
    "error",
    [
        FileExistsError(errno.EEXIST, "exists"),
        OSError(errno.EEXIST, "exists"),
        OSError(errno.ENOTEMPTY, "not empty"),
    ],
    ids=["FileExistsError", "EEXIST", "ENOTEMPTY"],
)
def test_the_systems_own_words_for_an_existing_target_are_snapshot_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pauses: list[float], error: OSError
) -> None:
    attempts = scripted_rename(monkeypatch, [error])
    with pytest.raises(SnapshotExists) as caught:
        write_snapshot(tmp_path, snap())
    assert len(attempts) == 1
    assert pauses == []
    assert caught.value.__cause__ is error
    assert list((tmp_path / RUN_ID / "acme-pricing").iterdir()) == []


def test_another_failure_is_raised_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pauses: list[float]
) -> None:
    attempts = scripted_rename(monkeypatch, [OSError(errno.EIO, "disk error"), None])
    with pytest.raises(OSError, match="disk error"):
        write_snapshot(tmp_path, snap())
    assert len(attempts) == 1
    assert pauses == []


def test_the_real_system_refuses_a_rename_onto_a_snapshot_that_exists(tmp_path: Path) -> None:
    # No scripting: whatever this system answers (denied on Windows, not empty elsewhere) has to
    # end as SnapshotExists, and the other writer's files stay as they were.
    target = tmp_path / "published"
    target.mkdir()
    (target / "meta.json").write_bytes(b"first")
    temporary = tmp_path / (".tmp-" + "0" * 16)
    temporary.mkdir()
    (temporary / "meta.json").write_bytes(b"second")
    with pytest.raises(SnapshotExists):
        snapshot_module._publish(temporary, target)
    assert (target / "meta.json").read_bytes() == b"first"


# --- folder permissions -------------------------------------------------------------------------


def test_the_temporary_folder_is_made_with_a_plain_mkdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made: list[tuple[str, int, bool]] = []
    real_mkdir = Path.mkdir

    def spy(self: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False) -> None:
        if self.name.startswith(".tmp-"):
            made.append((self.name, mode, exist_ok))
        real_mkdir(self, mode=mode, parents=parents, exist_ok=exist_ok)

    def no_mkdtemp(*args: object, **kwargs: object) -> str:
        raise AssertionError("tempfile.mkdtemp creates a folder that does not inherit its ACL")

    monkeypatch.setattr(Path, "mkdir", spy)
    monkeypatch.setattr(tempfile, "mkdtemp", no_mkdtemp)
    write_snapshot(tmp_path, snap())
    ((name, mode, exist_ok),) = made
    assert re.fullmatch(r"\.tmp-[0-9a-f]{16}", name)
    assert mode == 0o777  # the default, which leaves the permissions to the parent folder
    assert exist_ok is False


def icacls(path: Path) -> str:
    done = subprocess.run(["icacls", str(path)], capture_output=True, text=True, check=True)
    return done.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="ACL inheritance is a Windows matter")
def test_the_published_folder_inherits_its_permissions_like_any_other_folder(
    tmp_path: Path,
) -> None:
    ordinary = tmp_path / "ordinary"
    ordinary.mkdir()
    ref = write_snapshot(tmp_path, snap())
    inherited_here = "(I)" in icacls(ordinary)
    assert inherited_here, "the test folder itself does not inherit: nothing to compare"
    assert "(I)" in icacls(ref.path)  # a mkdtemp folder has a protected ACL: no (I) entries


# --- paths in UTF-16 units ----------------------------------------------------------------------


def test_a_character_outside_the_basic_plane_counts_twice_toward_the_path_limit(
    tmp_path: Path,
) -> None:
    emoji = chr(0x1F600)
    page_key, state_label = "k" * 32, "s" * 32
    base = tmp_path / "p"
    # By code points the longest path is MAX_PATH_CHARS, so a count of characters would allow it;
    # the emoji is two UTF-16 units, so Windows sees one more.
    pad = MAX_PATH_CHARS - longest_path(base, page_key, state_label) - 1  # 1 for the emoji's 2nd
    root = tmp_path / ("p" * (1 + pad) + emoji)
    longest_units = longest_path(root, page_key, state_label)
    assert longest_units == MAX_PATH_CHARS + 1
    assert len(str(root / RUN_ID / page_key / state_label / "structured.json")) <= MAX_PATH_CHARS
    with pytest.raises(ValueError, match="too long") as refused:
        write_snapshot(root, snap(page_key=page_key, state_label=state_label))
    assert str(longest_units) in str(refused.value)
    assert not root.exists()


def test_the_same_root_with_one_unit_fewer_is_written(tmp_path: Path) -> None:
    emoji = chr(0x1F600)
    page_key, state_label = "k" * 32, "s" * 32
    pad = MAX_PATH_CHARS - longest_path(tmp_path / "p", page_key, state_label) - 1
    root = tmp_path / ("p" * pad + emoji)
    assert longest_path(root, page_key, state_label) == MAX_PATH_CHARS
    ref = write_snapshot(root, snap(page_key=page_key, state_label=state_label))
    assert (ref.path / "structured.json").is_file()


# --- a relative root ----------------------------------------------------------------------------


def test_a_relative_root_gives_an_absolute_snapshot_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    ref = write_snapshot(Path("relative-root"), snap())
    assert ref.path.is_absolute()
    assert ref.path.parts[-4:] == ("relative-root", RUN_ID, "acme-pricing", "default")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # the path still names the snapshot after the directory changed
    assert (ref.path / "meta.json").is_file()
    assert read_meta(ref.path)["run_id"] == RUN_ID
