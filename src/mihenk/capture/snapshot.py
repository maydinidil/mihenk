"""Immutable snapshot folders (design §8.3): written once, never modified.

Layout: <root>/<run_id>/<page_key>/<state_label>/ with page.html (UTF-8), page.raw (the bytes
as received, fetch route only), text.txt (canonical text), structured.json, screenshot.png
(render routes only) and meta.json. The folder appears atomically, by renaming a temporary one.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mihenk import __version__
from mihenk.capture.locale import LocaleMarkers, markers_to_json
from mihenk.capture.models import SAFE_SEGMENT, Method
from mihenk.trim.structured import StructuredBlock, block_to_json

# Windows without LongPathsEnabled (the default) cannot write a path longer than 259 characters,
# and fails with a bare FileNotFoundError halfway through the write. The same limit applies on
# every platform, so a data folder that works on one machine works on all of them.
MAX_PATH_CHARS = 259
_TEMP_PREFIX = ".tmp-"
_TEMP_RANDOM_CHARS = 8  # what tempfile.mkdtemp appends to the prefix
_LONGEST_FILE = "structured.json"  # the longest file name in a snapshot folder


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


def new_run_id(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y%m%dt%H%M%Sz") + "-" + secrets.token_hex(3)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _longest_path_chars(target: Path) -> int:
    """The longest path `write_snapshot` will use for `target`: a file in the temporary sibling
    folder (`.tmp-` and 8 random characters, as `tempfile.mkdtemp` makes it) or in `target`."""
    parent = target.parent.absolute()
    temporary = parent / (_TEMP_PREFIX + "x" * _TEMP_RANDOM_CHARS) / _LONGEST_FILE
    final = parent / target.name / _LONGEST_FILE
    return max(len(str(temporary)), len(str(final)))


def write_snapshot(root: Path, snap: SnapshotInput) -> SnapshotRef:
    for segment in (snap.run_id, snap.page_key, snap.state_label):
        if not SAFE_SEGMENT.fullmatch(segment):
            raise ValueError(f"unsafe snapshot path segment: {segment!r}")
    if snap.captured_at.utcoffset() != timedelta(0):
        raise ValueError("captured_at must be a UTC time")
    target = root / snap.run_id / snap.page_key / snap.state_label
    longest = _longest_path_chars(target)
    if longest > MAX_PATH_CHARS:
        raise ValueError(
            f"snapshot path too long: {longest} characters, the limit is {MAX_PATH_CHARS}: {target}"
        )
    if target.exists():
        raise SnapshotExists(str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=_TEMP_PREFIX, dir=target.parent))
    try:
        html_bytes = snap.html.encode("utf-8")
        text_bytes = snap.text.encode("utf-8")
        (tmp / "page.html").write_bytes(html_bytes)
        (tmp / "text.txt").write_bytes(text_bytes)
        if snap.raw_bytes is not None:
            (tmp / "page.raw").write_bytes(snap.raw_bytes)
        if snap.screenshot_png is not None:
            (tmp / "screenshot.png").write_bytes(snap.screenshot_png)
        structured = [block_to_json(block) for block in snap.structured]
        (tmp / "structured.json").write_text(
            json.dumps(structured, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        ref = SnapshotRef(
            target,
            _sha256(html_bytes),
            _sha256(text_bytes),
            _sha256(snap.raw_bytes) if snap.raw_bytes is not None else None,
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
        }
        (tmp / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
        tmp.rename(target)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return ref
