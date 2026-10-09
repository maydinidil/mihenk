from __future__ import annotations

import pytest

from mihenk.trim.structured import (
    MAX_BLOCK_BYTES,
    StructuredKind,
    block_to_json,
    extract_structured,
)
from tests.helpers.pages import PAGES_DIR, STRUCTURED_KINDS, load_expectations, page_names

STRUCTURED_PAGES = [name for name in page_names() if "structured" in load_expectations(name)]


def _script(body: str, attrs: str = 'type="application/ld+json"') -> str:
    return f"<html><body><script {attrs}>{body}</script></body></html>"


def test_structured_kind_matches_the_kinds_the_trap_pages_may_name() -> None:
    assert {kind.value for kind in StructuredKind} == STRUCTURED_KINDS


def test_jsonld_parses() -> None:
    (block,) = extract_structured(_script('{"@type": "Offer", "price": "29"}'))
    assert block.kind is StructuredKind.JSONLD
    assert block.parsed == {"@type": "Offer", "price": "29"}
    assert block.problem is None
    assert block.raw is not None


def test_jsonld_inside_a_comment_wrapper_parses() -> None:
    (block,) = extract_structured(_script('<!--\n{"price": 29}\n-->'))
    assert block.parsed == {"price": 29}
    assert block.problem is None


def test_jsonld_inside_a_cdata_wrapper_parses() -> None:
    (block,) = extract_structured(_script('//<![CDATA[\n{"price": 29}\n//]]>'))
    assert block.parsed == {"price": 29}
    assert block.problem is None


def test_invalid_json_is_reported_not_raised() -> None:
    (block,) = extract_structured(_script('{"price": 29,}'))
    assert block.parsed is None
    assert block.problem is not None
    assert block.problem.startswith("invalid_json")
    assert block.raw == '{"price": 29,}'


def test_next_data_is_its_own_kind() -> None:
    html = _script('{"props": {}}', 'id="__NEXT_DATA__" type="application/json"')
    (block,) = extract_structured(html)
    assert block.kind is StructuredKind.NEXT_DATA
    assert block.script_id == "__NEXT_DATA__"
    assert block.parsed == {"props": {}}


def test_nuxt_data_is_its_own_kind() -> None:
    (block,) = extract_structured(_script("[1, 2]", 'id="__NUXT_DATA__" type="application/json"'))
    assert block.kind is StructuredKind.NUXT_DATA


def test_other_json_scripts_are_json_script() -> None:
    (block,) = extract_structured(_script('{"a": 1}', 'id="state" type="application/json"'))
    assert block.kind is StructuredKind.JSON_SCRIPT
    assert block.script_id == "state"


def test_the_type_is_matched_without_regard_to_case_or_padding() -> None:
    (block,) = extract_structured(_script("{}", 'type=" Application/LD+JSON "'))
    assert block.kind is StructuredKind.JSONLD


def test_javascript_and_untyped_scripts_are_ignored() -> None:
    html = (
        '<script type="text/javascript">{"a": 1}</script>'
        '<script>{"a": 1}</script>'
        '<script id="other">{"a": 1}</script>'
    )
    assert extract_structured(html) == []


def test_index_counts_every_script_on_the_page() -> None:
    html = '<script>var a;</script><script type="application/ld+json">{}</script>'
    (block,) = extract_structured(html)
    assert block.index == 1


def test_huge_json_block_is_marked_too_large() -> None:
    body = '{"pad": "' + "x" * 3_000_000 + '"}'
    (block,) = extract_structured(_script(body, 'type="application/json"'))
    assert block.kind is StructuredKind.JSON_SCRIPT
    assert block.problem == "too_large"
    assert block.raw is None
    assert block.parsed is None
    assert block.size_bytes > MAX_BLOCK_BYTES


def test_size_is_counted_in_utf8_bytes() -> None:
    body = '{"pad": "' + "€" * 700_000 + '"}'  # 700 thousand characters, 2.1 million bytes
    (block,) = extract_structured(_script(body))
    assert block.problem == "too_large"
    assert block.size_bytes > MAX_BLOCK_BYTES


def test_json_nested_too_deep_is_reported_not_raised() -> None:
    body = "[" * 100_000 + "]" * 100_000
    (block,) = extract_structured(_script(body))
    assert block.parsed is None
    assert block.problem == "invalid_json: nesting too deep"


def test_an_integer_with_thousands_of_digits_is_reported_not_raised() -> None:
    body = '{"price": ' + "9" * 5000 + "}"
    (block,) = extract_structured(_script(body))
    assert block.parsed is None
    assert block.problem == "invalid_json: number too long"


@pytest.mark.parametrize("name", STRUCTURED_PAGES)
def test_trap_pages_give_the_blocks_their_expectations_name(name: str) -> None:
    html = (PAGES_DIR / name / "page.html").read_text(encoding="utf-8")
    expected = load_expectations(name)["structured"]
    found = [(block.kind.value, block.problem) for block in extract_structured(html)]
    assert found == [(item["kind"], item["problem"]) for item in expected]


def test_block_to_json_keeps_raw_only_when_nothing_was_parsed() -> None:
    parsed_html = _script('{"a": 1}')
    (parsed,) = extract_structured(parsed_html)
    assert block_to_json(parsed) == {
        "kind": "jsonld",
        "index": 0,
        "script_id": None,
        "size_bytes": len('{"a": 1}'),
        "problem": None,
        "parsed": {"a": 1},
        "raw": None,
    }
    (broken,) = extract_structured(_script("{oops"))
    assert block_to_json(broken)["raw"] == "{oops"
    assert block_to_json(broken)["parsed"] is None
