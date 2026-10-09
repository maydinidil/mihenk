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


def _parse(text: str) -> tuple[object | None, str | None]:
    """Parse one block: `(parsed, None)`, or `(None, problem)` with the cause in plain words.

    Only JSON that can be written back out as valid UTF-8 JSON counts as parsed, because that is
    how snapshots store it. `json.loads` accepts more than that: `NaN`, `Infinity` and `1e999`
    (which parses to infinity) have no JSON form, and an escaped lone surrogate has no UTF-8 form.
    """
    try:
        parsed: object = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"invalid_json: {exc.msg}"
    except RecursionError:
        return None, "invalid_json: nesting too deep"
    except ValueError:
        # The only other thing json.loads raises is the limit on an integer's digits.
        return None, "invalid_json: number too long"
    try:
        json.dumps(parsed, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except RecursionError:
        return None, "invalid_json: nesting too deep"
    except UnicodeEncodeError:
        return None, "invalid_json: unpaired surrogate"
    except ValueError:
        # With allow_nan off, a float that is NaN or infinite is the only ValueError dumps gives.
        return None, "invalid_json: non-finite number"
    return parsed, None


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
        # "surrogatepass": a lone surrogate in the text still has a size (3 bytes), not an error.
        size = len(raw.encode("utf-8", "surrogatepass"))
        if size > MAX_BLOCK_BYTES:
            blocks.append(StructuredBlock(kind, index, sid, None, size, None, "too_large"))
            continue
        parsed, problem = _parse(_strip_wrappers(raw))
        blocks.append(StructuredBlock(kind, index, sid, raw, size, parsed, problem))
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
