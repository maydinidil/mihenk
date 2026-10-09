import time

import pytest

from mihenk.capture.locale import detect_locale_markers, markers_to_json
from mihenk.trim.text import html_to_text
from tests.helpers.pages import PAGES_DIR, load_expectations, page_names


def markers(text: str, html: str = "<html lang='en'>", headers: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
    return detect_locale_markers(html, text, headers or {})


@pytest.mark.parametrize(
    ("text", "language", "kind"),
    [
        ("€29 incl. VAT", "en", "incl"),
        ("£19 + VAT", "en", "excl"),
        ("€25 excl. btw", "nl", "excl"),
        ("€25 inclusief btw", "nl", "incl"),
        ("29 € inkl. 19 % MwSt.", "de", "incl"),
        ("29 € zzgl. MwSt.", "de", "excl"),
        ("29 € HT", "fr", "excl"),
        ("29 € TTC", "fr", "incl"),
        ("29 € IVA incluido", "es", "incl"),
        ("29 € IVA no incluido", "es", "excl"),
        ("29 € + IVA", "it", "excl"),
        ("Fiyatlara KDV dahildir", "tr", "incl"),
        ("199 TL KDV DAHİL", "tr", "incl"),
        ("199 TL + KDV", "tr", "excl"),
        ("199 TL KDV HARİÇ", "tr", "excl"),
    ],
)
def test_vat_phrases(text: str, language: str, kind: str) -> None:
    found = markers(text).vat_phrases
    assert (language, kind) in {(p.language, p.kind) for p in found}


def test_iva_no_incluido_is_not_reported_as_included() -> None:
    kinds = {(p.language, p.kind) for p in markers("29 € IVA no incluido").vat_phrases}
    assert ("es", "incl") not in kinds


def test_plus_iva_is_both_spanish_and_italian_wording() -> None:
    # The two languages share the wording; the page language decides later, not this module.
    kinds = {(p.language, p.kind) for p in markers("22 € + IVA").vat_phrases}
    assert {("es", "excl"), ("it", "excl")} <= kinds


def test_symbols_and_codes_next_to_numbers() -> None:
    found = markers("Basic €9, Pro 29 USD, Team 405 Kč, Try it free")
    assert "€" in found.currency_symbols
    assert "Kč" in found.currency_symbols
    assert found.currency_codes == ("USD",)


def test_language_signals() -> None:
    found = markers(
        "x", html="<html lang='nl-NL'><body>x</body></html>", headers={"content-language": "nl"}
    )
    assert (found.html_lang, found.content_language) == ("nl-NL", "nl")


def test_a_long_run_of_digits_and_spaces_is_scanned_in_linear_time() -> None:
    text = "1 " * 50_000
    started = time.monotonic()
    found = markers(text)
    elapsed = time.monotonic() - started
    assert found.currency_codes == ()
    assert elapsed < 2


def test_markers_to_json_is_plain_data() -> None:
    found = markers("29 € HT", html="<html lang='fr'>")
    assert markers_to_json(found) == {
        "html_lang": "fr",
        "content_language": None,
        "currency_symbols": ["€"],
        "currency_codes": [],
        "vat_phrases": [{"language": "fr", "kind": "excl", "phrase": "HT"}],
    }


LOCALE_PAGES = [name for name in page_names() if "locale" in load_expectations(name)]


def test_the_seven_vat_pages_are_covered() -> None:
    vat_pages = {name for name in page_names() if name.startswith("vat-")}
    assert len(vat_pages) == 7
    assert vat_pages <= set(LOCALE_PAGES)


@pytest.mark.parametrize("name", LOCALE_PAGES)
def test_trap_page_locale_markers(name: str) -> None:
    # Only `windows-1254` is not UTF-8 (the same rule as tests/unit/test_trap_pages.py).
    encoding = "cp1254" if name == "windows-1254" else "utf-8"
    html = (PAGES_DIR / name / "page.html").read_bytes().decode(encoding)
    found = detect_locale_markers(html, html_to_text(html), {})
    expected = load_expectations(name)["locale"]
    if "html_lang" in expected:
        assert found.html_lang == expected["html_lang"]
    if "content_language" in expected:
        assert found.content_language == expected["content_language"]
    if "currency_symbols" in expected:
        assert list(found.currency_symbols) == expected["currency_symbols"]
    if "currency_codes" in expected:
        assert list(found.currency_codes) == expected["currency_codes"]
    # By containment: the same wording can belong to two languages ("+ IVA"), so extra phrases
    # are allowed and the page language decides later.
    got = {(p.language, p.kind, p.phrase) for p in found.vat_phrases}
    for phrase in expected.get("vat_phrases", []):
        assert (phrase["language"], phrase["kind"], phrase["phrase"]) in got
