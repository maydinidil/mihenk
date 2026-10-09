"""Locale markers: signals about which country's page this is (design §8.3, §8.8).

Turkish letters are spelled out in character classes rather than relying on case-insensitive
matching, because İ and ı do not fold to i like English letters do.
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
_VAT: tuple[tuple[str, VatKind, re.Pattern[str]], ...] = (
    ("en", "excl", re.compile(r"(?:\b(?:excl(?:\.|uding)?|ex\.?|plus)\s*|\+\s*)VAT\b", _I)),
    ("en", "incl", re.compile(r"\b(?:incl(?:\.|uding)?|inc\.?)\s*VAT\b|\bVAT\s+included\b", _I)),
    ("nl", "excl", re.compile(r"(?:\b(?:excl(?:\.|usief)?|ex\.?)\s*|\+\s*)btw\b", _I)),
    ("nl", "incl", re.compile(r"\b(?:incl(?:\.|usief)?)\s*btw\b", _I)),
    (
        "de",
        "excl",
        re.compile(
            r"\b(?:zzgl\.?|zuzüglich|exkl\.?|exklusive)\s*(?:\d{1,2}\s*%\s*)?(?:MwSt|USt)\b", _I
        ),
    ),
    ("de", "incl", re.compile(r"\b(?:inkl\.?|inklusive)\s*(?:\d{1,2}\s*%\s*)?(?:MwSt|USt)\b", _I)),
    ("fr", "excl", re.compile(r"(?<![\w-])HT(?![\w-])")),
    ("fr", "incl", re.compile(r"(?<![\w-])TTC(?![\w-])")),
    (
        "es",
        "excl",
        re.compile(r"(?:\bmás\s*|\+\s*)IVA\b|\bIVA\s+no\s+incluido\b|\bsin\s+IVA\b", _I),
    ),
    ("es", "incl", re.compile(r"\bIVA\s+incluido\b", _I)),
    ("it", "excl", re.compile(r"(?:\bpiù\s*|\+\s*)IVA\b|\bIVA\s+esclusa\b", _I)),
    ("it", "incl", re.compile(r"\bIVA\s+(?:inclusa|compresa)\b|\bincl\.?\s*IVA\b", _I)),
    ("tr", "excl", re.compile(r"\+\s*KDV\b|\bKDV\s*har[iİı][çÇcC]|\bKDV['’]?s[iİı]z\b", _I)),
    ("tr", "incl", re.compile(r"\bKDV\s*d[aâ]h[iİı]l", _I)),
)
_FREE_SYMBOLS = ("€", "£", "¥", "₺", "₹", "₽", "₩", "$")
_WORD_SYMBOLS = ("zł", "Kč", "kr", "CHF", "TL", "R$")
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
)
# Only the number's last digit matters, so this is a digit and at most two separators. A pattern
# that swallowed the whole run of digits and spaces would backtrack quadratically on a long run.
_NUM_END = r"\d[.,\u00a0 ]{0,2}"


def _beside_number(token: str, text: str) -> bool:
    escaped = re.escape(token)
    pattern = rf"(?:{_NUM_END}\s?{escaped}(?![\w]))|(?:(?<![\w]){escaped}\s?\d)"
    return re.search(pattern, text) is not None


def detect_locale_markers(html: str, text: str, headers: Mapping[str, str]) -> LocaleMarkers:
    root = BeautifulSoup(html[:200_000], "html.parser").find("html")
    lang = root.get("lang") if root is not None and hasattr(root, "get") else None
    symbols = sorted(
        {s for s in _FREE_SYMBOLS if s in text}
        | {s for s in _WORD_SYMBOLS if _beside_number(s, text)}
    )
    codes = sorted(c for c in _CODES if _beside_number(c, text))
    phrases: list[VatPhrase] = []
    for language, kind, pattern in _VAT:
        phrases.extend(VatPhrase(language, kind, m.group(0)) for m in pattern.finditer(text))
    return LocaleMarkers(
        html_lang=lang if isinstance(lang, str) else None,
        content_language={k.lower(): v for k, v in headers.items()}.get("content-language"),
        currency_symbols=tuple(symbols),
        currency_codes=tuple(codes),
        vat_phrases=tuple(phrases),
    )


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
