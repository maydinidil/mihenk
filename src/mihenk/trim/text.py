"""The one canonical form of page text (design §8.5, §8.6).

Every snapshot stores this form, the LLM sees exactly this form, and quotes are matched
against it. Normalising here, once, before anyone quotes from it, is safe; normalising the
page at match time is not (§8.6).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator

from bs4 import BeautifulSoup, Tag
from bs4.element import (
    CData,
    Comment,
    Declaration,
    Doctype,
    NavigableString,
    PageElement,
    ProcessingInstruction,
)

_Frame = tuple[Iterator[PageElement], bool, bool]

_HSPACE = re.compile(r"[ \t\f\v\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]+")
_INVISIBLE = re.compile(r"[\u200b\ufeff]")
# A rendered DOM can hold half of a surrogate pair. Writing it into a snapshot would raise
# `UnicodeEncodeError`, so it becomes U+FFFD, which is what a UTF-8 decoder would show.
_LONE_SURROGATE = re.compile("[\ud800-\udfff]")
# <br> is not here: `html_to_text` turns it into a line break by name, before this set is asked.
_BLOCK = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "caption",
        "dd",
        "details",
        "dialog",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "legend",
        "li",
        "main",
        "nav",
        "ol",
        "optgroup",
        "option",
        "p",
        "pre",
        "section",
        "summary",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
)
# "title" stands in for "head": html.parser never closes an open <head>, so a page that omits
# </head> nests its whole body inside it, and skipping "head" would drop every word of text.
_SKIP = frozenset({"script", "style", "noscript", "template", "title", "iframe", "object", "path"})
_NOT_TEXT = (Comment, CData, Declaration, Doctype, ProcessingInstruction)


def scrub_surrogates(text: str) -> str:
    """The text with every lone surrogate (U+D800 to U+DFFF) replaced by U+FFFD.

    UTF-8 cannot encode a surrogate, so one left in page text or HTML would make writing a
    snapshot raise `UnicodeEncodeError` and lose the capture.
    """
    return _LONE_SURROGATE.sub("\N{REPLACEMENT CHARACTER}", text)


def canonical_text(raw: str) -> str:
    # The invisible characters go first: one between a letter and its accent would otherwise
    # stop NFC from composing them, and a second call would compose them (not idempotent).
    text = unicodedata.normalize("NFC", _INVISIBLE.sub("", raw))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_HSPACE.sub(" ", line).strip() for line in text.split("\n")]
    joined = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return joined + "\n" if joined else ""


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    parts: list[str] = []
    # An explicit stack instead of recursion: html.parser never closes an <li>, <p> or <td>, so a
    # valid page of a few thousand list items nests that deep and would overflow the call stack.
    # Each frame is the children still to visit, whether we are inside <pre>, and whether the
    # element is a block, whose closing line break is written when its children run out.
    stack: list[_Frame] = [(iter(soup.children), False, False)]
    while stack:
        children, in_pre, closing_break = stack[-1]
        for child in children:
            if isinstance(child, _NOT_TEXT):
                continue
            if isinstance(child, NavigableString):
                parts.append(str(child) if in_pre else re.sub(r"\s+", " ", str(child)))
                continue
            if not isinstance(child, Tag):
                continue
            name = child.name.lower()
            if name in _SKIP or child.has_attr("hidden"):
                continue
            if name == "br":
                parts.append("\n")
                continue
            block = name in _BLOCK
            if block:
                parts.append("\n")
            stack.append((iter(child.children), in_pre or name == "pre", block))
            break
        else:
            stack.pop()
            if closing_break:
                parts.append("\n")
    # One line per block: block edges never produce blank lines on the fetch route.
    return canonical_text(re.sub(r"\n[ \t]*(?:\n[ \t]*)+", "\n", "".join(parts)))
