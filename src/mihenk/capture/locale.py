"""Locale markers: signals about which country's page this is (design §8.3, §8.8).

Turkish letters are spelled out in character classes (`[çÇcC]`, `[gğ]`, `[iİı]`) and not left to
case-insensitive matching. Python's IGNORECASE does fold İ and ı to i, so `[iİı]` would work
without the class, but it does not fold ç, ğ or ş to c, g or s, and Turkish prices are often typed
without those accents ("KDV haric", "degil"). The classes accept the page either way.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from bs4 import BeautifulSoup

VatKind = Literal["incl", "excl"]


@dataclass(frozen=True)
class VatPhrase:
    language: str
    kind: VatKind
    phrase: str


@dataclass(frozen=True)
class LocaleMarkers:
    html_lang: str | None
    content_language: str | None
    currency_symbols: tuple[str, ...]
    currency_codes: tuple[str, ...]
    vat_phrases: tuple[VatPhrase, ...]


_I = re.IGNORECASE
# A rate between the word and the tax name: "plus 21% VAT", "inkl. 19 % MwSt.".
_RATE = r"(?:\d{1,2}(?:[.,]\d+)?\s*%\s*)?"
# A tax name followed by an ID word is a tax registration line ("Acme Inc. VAT ID: 123"), not a
# statement about prices. "No" must be written with a capital: "incl. VAT no hidden fees" is a
# price statement.
_EN_ID = r"(?![\s-]*(?:ID(?:s|entification)?\b|(?-i:No|NO)\b|number|reg(?:istr\w*)?\b))"
_NL_ID = r"(?![\s-]*(?:nummer|nr\b|id\b))"
_DE_ID = r"(?![\s-]*Id(?:Nr|\b))"
_VAT: tuple[tuple[str, VatKind, re.Pattern[str]], ...] = (
    (
        "en",
        "excl",
        re.compile(
            r"(?:\b(?:excl(?:\.|uding|usive(?:\s+of)?)?|ex\.?|plus)\s*|\+\s*)"
            + _RATE
            + r"VAT\b"
            + _EN_ID
            + r"|\bVAT\s+excluded\b",
            _I,
        ),
    ),
    (
        "en",
        "incl",
        re.compile(
            r"(?<!not\s)(?:\b(?:incl(?:\.|uding|usive(?:\s+of)?)?|inc\.?)\s*"
            + _RATE
            + r"VAT\b"
            + _EN_ID
            + r"|\bVAT\s+included\b)",
            _I,
        ),
    ),
    (
        "nl",
        "excl",
        re.compile(r"(?:\b(?:excl(?:\.|usief)?|ex\.?)\s*|\+\s*)" + _RATE + r"btw\b" + _NL_ID, _I),
    ),
    (
        "nl",
        "incl",
        re.compile(r"(?<!niet\s)\b(?:incl(?:\.|usief)?)\s*" + _RATE + r"btw\b" + _NL_ID, _I),
    ),
    (
        "de",
        "excl",
        re.compile(
            r"\b(?:zzgl\.?|zuzüglich|exkl\.?|exklusive|ohne)\s*"
            + _RATE
            + r"(?:gesetzl(?:\.|iche?[rnsm]?)?\s*)?(?:MwSt|USt)\b"
            + _DE_ID,
            _I,
        ),
    ),
    (
        "de",
        "incl",
        re.compile(
            r"(?<!nicht\s)\b(?:inkl\.?|inklusive)\s*"
            + _RATE
            + r"(?:gesetzl(?:\.|iche?[rnsm]?)?\s*)?(?:MwSt|USt)\b"
            + _DE_ID,
            _I,
        ),
    ),
    ("fr", "excl", re.compile(r"(?<![\w-])HT(?![\w-])|(?i:\bhors[\s-]+TVA\b)")),
    ("fr", "incl", re.compile(r"(?<![\w-])TTC(?![\w-])|(?i:\bTVA\s+incluse\b)")),
    (
        "es",
        "excl",
        re.compile(r"(?:\bmás\s*|\+\s*)IVA\b|\bIVA\s+no\s+incluido\b|\bsin\s+IVA\b", _I),
    ),
    ("es", "incl", re.compile(r"\bIVA\s+incluido\b", _I)),
    (
        "it",
        "excl",
        re.compile(r"(?:\bpiù\s*|\+\s*)IVA\b|\bIVA\s+esclusa\b|\bIVA\s+non\s+incl(?:usa)?\b", _I),
    ),
    (
        "it",
        "incl",
        re.compile(r"\bIVA\s+(?:inclusa|compresa|incl\b\.?)|\bincl\.?\s*IVA\b", _I),
    ),
    (
        "tr",
        "excl",
        re.compile(
            r"\+\s*KDV\b|\bKDV\s*har[iİı][çÇcC]|\bKDV['’]?s[iİı]z\b"
            r"|\bKDV(?:['’]?s[iİı])?\s*(?:%\s*\d{1,2}\s*)?d[aâ]h[iİı]l\w*\s+de[gğ][iİı]l",
            _I,
        ),
    ),
    (
        "tr",
        "incl",
        re.compile(
            r"\bKDV(?:['’]?s[iİı])?\s*(?:%\s*\d{1,2}\s*)?d[aâ]h[iİı]l(?!\w*\s+de[gğ][iİı]l)", _I
        ),
    ),
)
_FREE_SYMBOLS = ("€", "£", "¥", "₺", "₹", "₽", "₩", "$")
_WORD_SYMBOLS = ("zł", "Kč", "kr", "CHF", "TL", "R$")
# `R$` is a sign of its own (above), and the same goes for A$, C$, US$, HK$, S$ and the like: the
# `$` in them is not a dollar sign. One to three capitals right before it make it part of a sign.
_PREFIXED_DOLLAR = re.compile(r"(?<![A-Za-z])[A-Z]{1,3}\$")
_CODES = (
    "EUR",
    "USD",
    "GBP",
    "CHF",
    "SEK",
    "NOK",
    "DKK",
    "PLN",
    "CZK",
    "HUF",
    "RON",
    "TRY",
    "JPY",
    "CNY",
    "INR",
    "AUD",
    "CAD",
    "NZD",
    "BRL",
    "MXN",
    "ZAR",
    "AED",
    "KRW",
    "SGD",
    "HKD",
)
# Only the number's last digit matters, so this is a digit and at most two separators. A pattern
# that swallowed the whole run of digits and spaces would backtrack quadratically on a long run.
_NUM_END = r"\d[.,\u00a0 ]{0,2}"
# "29 euro", "29 euros": the word counts as EUR after a number only. Before one it is not a
# currency ("EURO 5" is an emission standard).
_EURO_WORD = re.compile(rf"{_NUM_END}\s?euros?(?![\w])", re.IGNORECASE)


def _beside_number(token: str, text: str) -> bool:
    escaped = re.escape(token)
    pattern = rf"(?:{_NUM_END}\s?{escaped}(?![\w]))|(?:(?<![\w]){escaped}\s?\d)"
    return re.search(pattern, text) is not None


def _symbol_beside_number(symbol: str, text: str) -> bool:
    """Whether a sign that is not a letter stands next to a number, before or after it.

    A currency switcher ("€ EUR | £ GBP | $ USD") has the signs and no numbers, so it says
    nothing about the price. No word boundary is asked for: "From€9" is a price too.
    """
    if symbol == "$":
        text = _PREFIXED_DOLLAR.sub(" ", text)
    escaped = re.escape(symbol)
    return re.search(rf"(?:{_NUM_END}\s?{escaped})|(?:{escaped}\s?\d)", text) is not None


def detect_locale_markers(html: str, text: str, headers: Mapping[str, str]) -> LocaleMarkers:
    root = BeautifulSoup(html[:200_000], "html.parser").find("html")
    lang = root.get("lang") if root is not None and hasattr(root, "get") else None
    symbols = sorted(
        {s for s in _FREE_SYMBOLS if s in text and _symbol_beside_number(s, text)}
        | {s for s in _WORD_SYMBOLS if _beside_number(s, text)}
    )
    codes = {c for c in _CODES if _beside_number(c, text)}
    if _EURO_WORD.search(text):
        codes.add("EUR")
    # One entry per (language, kind, phrase), in the order each was first found: a price table
    # that says "excl. VAT" in every row is one statement, not a thousand.
    phrases = dict.fromkeys(
        VatPhrase(language, kind, m.group(0))
        for language, kind, pattern in _VAT
        for m in pattern.finditer(text)
    )
    content_language = {k.lower(): v for k, v in headers.items()}.get("content-language")
    return LocaleMarkers(
        html_lang=_clean(lang),
        content_language=_clean(content_language),
        currency_symbols=tuple(symbols),
        currency_codes=tuple(sorted(codes)),
        vat_phrases=tuple(phrases),
    )


def _clean(value: object) -> str | None:
    """A language tag without the padding around it; an empty one is no signal at all."""
    if not isinstance(value, str):
        return None
    return value.strip() or None


def markers_to_json(markers: LocaleMarkers) -> dict[str, object]:
    return {
        "html_lang": markers.html_lang,
        "content_language": markers.content_language,
        "currency_symbols": list(markers.currency_symbols),
        "currency_codes": list(markers.currency_codes),
        "vat_phrases": [
            {"language": p.language, "kind": p.kind, "phrase": p.phrase}
            for p in markers.vat_phrases
        ],
    }
