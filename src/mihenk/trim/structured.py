"""JSON-LD and framework data found in a page (design §8.3). No extruct (§22)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

from bs4 import BeautifulSoup, Tag

MAX_BLOCK_BYTES = 2_000_000
_WRAPPERS = (("<!--", "-->"), ("//<![CDATA[", "//]]>"), ("<![CDATA[", "]]>"))


class StructuredKind(StrEnum):
    JSONLD = "jsonld"
    NEXT_DATA = "next_data"
    NUXT_DATA = "nuxt_data"
    JSON_SCRIPT = "json_script"


@dataclass(frozen=True)
class StructuredBlock:
    kind: StructuredKind
    index: int
    script_id: str | None
    raw: str | None
    size_bytes: int
    parsed: object | None
    problem: str | None


def _kind(script: Tag) -> StructuredKind | None:
    script_type = str(script.get("type") or "").strip().lower()
    script_id = script.get("id")
    if script_type == "application/ld+json":
        return StructuredKind.JSONLD
    if script_id == "__NEXT_DATA__":
        return StructuredKind.NEXT_DATA
    if script_id == "__NUXT_DATA__":
        return StructuredKind.NUXT_DATA
    if script_type == "application/json":
        return StructuredKind.JSON_SCRIPT
    return None


def _strip_wrappers(raw: str) -> str:
    text = raw.strip()
    for prefix, suffix in _WRAPPERS:
        if text.startswith(prefix) and text.endswith(suffix):
            text = text[len(prefix) : -len(suffix)].strip()
    return text


def _json_problem(exc: ValueError | RecursionError) -> str:
    """Why `json.loads` gave up, in plain words.

    A page can hold JSON that makes the parser raise something other than a decode error: a
    deeply nested block overflows the stack, and an integer of more than 4300 digits is refused.
    """
    if isinstance(exc, json.JSONDecodeError):
        return f"invalid_json: {exc.msg}"
    if isinstance(exc, RecursionError):
        return "invalid_json: nesting too deep"
    return "invalid_json: number too long"


def extract_structured(html: str) -> list[StructuredBlock]:
    blocks: list[StructuredBlock] = []
    for index, script in enumerate(BeautifulSoup(html, "html.parser").find_all("script")):
        if not isinstance(script, Tag):
            continue
        kind = _kind(script)
        if kind is None:
            continue
        raw = script.get_text()
        script_id = script.get("id")
        sid = script_id if isinstance(script_id, str) else None
        size = len(raw.encode("utf-8"))
        if size > MAX_BLOCK_BYTES:
            blocks.append(StructuredBlock(kind, index, sid, None, size, None, "too_large"))
            continue
        try:
            parsed: object = json.loads(_strip_wrappers(raw))
        except (ValueError, RecursionError) as exc:
            blocks.append(StructuredBlock(kind, index, sid, raw, size, None, _json_problem(exc)))
        else:
            blocks.append(StructuredBlock(kind, index, sid, raw, size, parsed, None))
    return blocks


def block_to_json(block: StructuredBlock) -> dict[str, object]:
    return {
        "kind": block.kind.value,
        "index": block.index,
        "script_id": block.script_id,
        "size_bytes": block.size_bytes,
        "problem": block.problem,
        "parsed": block.parsed,
        "raw": block.raw if block.parsed is None else None,
    }
