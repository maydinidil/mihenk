"""Immutable snapshot folders (design §8.3): written once, never modified.

Layout: <root>/<run_id>/<page_key>/<state_label>/ with page.html (UTF-8), page.raw (the bytes
as received, fetch route only), text.txt (canonical text), structured.json, screenshot.png
(render routes only) and meta.json. The folder appears atomically, by renaming a temporary one.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import secrets
import shutil
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mihenk import __version__
from mihenk.capture.locale import LocaleMarkers, markers_to_json
from mihenk.capture.models import SAFE_SEGMENT, Method
from mihenk.trim.structured import StructuredBlock, block_to_json
from mihenk.trim.text import scrub_surrogates

# Windows without LongPathsEnabled (the default) cannot write a path longer than 259 characters,
# and fails with a bare FileNotFoundError halfway through the write. The same limit applies on
# every platform, so a data folder that works on one machine works on all of them. Windows counts
# UTF-16 code units, so a character outside the Basic Multilingual Plane (an emoji) counts twice.
MAX_PATH_CHARS = 259
_TEMP_PREFIX = ".tmp-"
_TEMP_RANDOM_BYTES = 8  # `secrets.token_hex(8)` is 16 characters
_TEMP_RANDOM_CHARS = 2 * _TEMP_RANDOM_BYTES
_LONGEST_FILE = "structured.json"  # the longest file name in a snapshot folder
# An antivirus scanner or the search indexer can hold the new folder for a moment, and Windows
# then refuses the rename with PermissionError. A few short retries get past it.
_RENAME_RETRIES = 5  # after the first attempt, so a rename is tried up to six times
_RENAME_PAUSE_S = 0.1
# Windows cannot open a folder to flush it; everywhere else the new name is not durable until the
# folder that holds it has been flushed too.
_CAN_SYNC_FOLDERS = os.name != "nt"


class SnapshotExists(FileExistsError):
    pass


@dataclass(frozen=True)
class SnapshotInput:
    run_id: str
    page_key: str
    state_label: str
    url: str
    final_url: str
    http_status: int | None
    method: Method
    captured_at: datetime
    html: str
    raw_bytes: bytes | None
    encoding: str | None
    text: str
    structured: Sequence[StructuredBlock]
    screenshot_png: bytes | None
    locale: LocaleMarkers
    collection_country: str


@dataclass(frozen=True)
class SnapshotRef:
    path: Path
    html_sha256: str
    text_sha256: str
    raw_sha256: str | None
    # SHA-256 of every file in the folder except meta.json, which holds this map. A snapshot is
    # immutable, so a file written without a hash here can never get one later.
    files: Mapping[str, str]


def new_run_id(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y%m%dt%H%M%Sz") + "-" + secrets.token_hex(3)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object, *, indent: int, sort_keys: bool = False) -> bytes:
    """JSON as UTF-8 bytes. A lone surrogate in any string (a URL, a locale value, the raw text of
    a bad block) has no UTF-8 form, so it is scrubbed from the finished text."""
    text = json.dumps(value, ensure_ascii=False, indent=indent, sort_keys=sort_keys)
    return scrub_surrogates(text).encode("utf-8")


def _utf16_units(path: Path) -> int:
    return len(str(path).encode("utf-16-le", "surrogatepass")) // 2


def _longest_path_chars(target: Path) -> int:
    """The longest path `write_snapshot` will use for `target`, in the UTF-16 code units that
    Windows counts: a file in the temporary sibling folder (`.tmp-` and 16 random characters) or
    in `target`."""
    parent = target.parent.absolute()
    temporary = parent / (_TEMP_PREFIX + "x" * _TEMP_RANDOM_CHARS) / _LONGEST_FILE
    final = parent / target.name / _LONGEST_FILE
    return max(_utf16_units(temporary), _utf16_units(final))


def _write_durably(path: Path, data: bytes) -> None:
    """Write a new file and flush it to the disk, so a power cut after the rename cannot leave a
    folder whose files are empty."""
    with path.open("xb") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())


def _sync_folder(folder: Path) -> None:
    """Flush a folder's entries to the disk. Best effort: not every file system allows it."""
    if not _CAN_SYNC_FOLDERS:
        return
    try:
        descriptor = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _publish(tmp: Path, target: Path) -> None:
    """Rename the finished temporary folder to its final name.

    A target that exists is `SnapshotExists`, whatever the system called the error: another writer
    got there first. Otherwise a `PermissionError` is retried, `_RENAME_RETRIES` times at most.
    """
    for retry in range(_RENAME_RETRIES + 1):
        try:
            tmp.rename(target)
        except OSError as exc:
            exists = (
                isinstance(exc, FileExistsError)
                or exc.errno in (errno.EEXIST, errno.ENOTEMPTY)
                or target.exists()
            )
            if exists:
                raise SnapshotExists(str(target)) from exc
            if not isinstance(exc, PermissionError) or retry == _RENAME_RETRIES:
                raise
            time.sleep(_RENAME_PAUSE_S)
        else:
            return


def write_snapshot(root: Path, snap: SnapshotInput) -> SnapshotRef:
    for segment in (snap.run_id, snap.page_key, snap.state_label):
        if not SAFE_SEGMENT.fullmatch(segment):
            raise ValueError(f"unsafe snapshot path segment: {segment!r}")
    if snap.captured_at.utcoffset() != timedelta(0):
        raise ValueError("captured_at must be a UTC time")
    # An absolute root, so the `SnapshotRef.path` that callers keep does not depend on the
    # working directory of the moment they read it.
    target = root.absolute() / snap.run_id / snap.page_key / snap.state_label
    longest = _longest_path_chars(target)
    if longest > MAX_PATH_CHARS:
        raise ValueError(
            f"snapshot path too long: {longest} characters, the limit is {MAX_PATH_CHARS}: {target}"
        )
    if target.exists():
        raise SnapshotExists(str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    # Not `tempfile.mkdtemp`: it creates the folder with mode 0o700, which on Windows (Python 3.13)
    # gives it, and so the published folder, a protected ACL that does not inherit from the data
    # folder. A plain `mkdir` inherits like any other folder.
    tmp = target.parent / (_TEMP_PREFIX + secrets.token_hex(_TEMP_RANDOM_BYTES))
    tmp.mkdir()
    try:
        # Every file is written as bytes and hashed over those same bytes. JSON is encoded here,
        # once, because `write_text` would turn "\n" into "\r\n" on Windows and the same snapshot
        # would then hash differently on Windows and macOS. Text is scrubbed of lone surrogates
        # first: UTF-8 has no form for one, and the capture would be lost to a
        # `UnicodeEncodeError` for a single bad character.
        contents: dict[str, bytes] = {
            "page.html": scrub_surrogates(snap.html).encode("utf-8"),
            "text.txt": scrub_surrogates(snap.text).encode("utf-8"),
        }
        if snap.raw_bytes is not None:
            contents["page.raw"] = snap.raw_bytes
        if snap.screenshot_png is not None:
            contents["screenshot.png"] = snap.screenshot_png
        structured = [block_to_json(block) for block in snap.structured]
        contents["structured.json"] = _json_bytes(structured, indent=2)
        for name, data in contents.items():
            _write_durably(tmp / name, data)
        files = {name: _sha256(data) for name, data in contents.items()}
        ref = SnapshotRef(
            target,
            files["page.html"],
            files["text.txt"],
            files.get("page.raw"),
            files,
        )
        meta = {
            "app_version": __version__,
            "run_id": snap.run_id,
            "page_key": snap.page_key,
            "state_label": snap.state_label,
            "url": snap.url,
            "final_url": snap.final_url,
            "http_status": snap.http_status,
            "method": snap.method.value,
            "captured_at": snap.captured_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "encoding": snap.encoding,
            "collection_country": snap.collection_country,
            "locale": markers_to_json(snap.locale),
            "html_sha256": ref.html_sha256,
            "text_sha256": ref.text_sha256,
            "raw_sha256": ref.raw_sha256,
            "files": files,
        }
        _write_durably(tmp / "meta.json", _json_bytes(meta, indent=2, sort_keys=True))
        _sync_folder(tmp)
        _publish(tmp, target)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    _sync_folder(target.parent)
    return ref
