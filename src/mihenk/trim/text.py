"""The one canonical form of page text (design §8.5, §8.6).

Every snapshot stores this form, the LLM sees exactly this form, and quotes are matched
against it. Normalising here, once, before anyone quotes from it, is safe; normalising the
page at match time is not (§8.6).
"""

from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup, Tag
from bs4.element import (
    CData,
    Comment,
    Declaration,
    Doctype,
    NavigableString,
    ProcessingInstruction,
)

_HSPACE = re.compile(r"[ \t\f\v\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]+")
_INVISIBLE = re.compile(r"[\u200b\ufeff]")
_BLOCK = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
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
        "li",
        "main",
        "nav",
        "ol",
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


def canonical_text(raw: str) -> str:
    text = unicodedata.normalize("NFC", raw).replace("\r\n", "\n").replace("\r", "\n")
    text = _INVISIBLE.sub("", text)
    lines = [_HSPACE.sub(" ", line).strip() for line in text.split("\n")]
    joined = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return joined + "\n" if joined else ""


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    parts: list[str] = []

    def walk(node: Tag, in_pre: bool) -> None:
        for child in node.children:
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
            walk(child, in_pre or name == "pre")
            if block:
                parts.append("\n")

    walk(soup, in_pre=False)
    # One line per block: block edges never produce blank lines on the fetch route.
    return canonical_text(re.sub(r"\n[ \t]*(?:\n[ \t]*)+", "\n", "".join(parts)))
