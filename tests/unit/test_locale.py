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


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("Fiyatlara KDV dahil değildir", "tr"),
        ("KDV dahil değildir.", "tr"),
        ("199 TL KDV DAHİL DEĞİLDİR", "tr"),
        ("€25 niet inclusief btw", "nl"),
        ("€25 Niet incl. btw", "nl"),
        ("29 € nicht inkl. MwSt.", "de"),
        ("29 € nicht inklusive 19 % MwSt.", "de"),
        ("€9 not incl. VAT", "en"),
        ("€9 Not including VAT", "en"),
    ],
)
def test_negated_wording_is_not_reported_as_included(text: str, language: str) -> None:
    kinds = {(p.language, p.kind) for p in markers(text).vat_phrases}
    assert (language, "incl") not in kinds


@pytest.mark.parametrize(
    "text",
    ["Fiyatlara KDV dahil değildir", "KDV dahil değildir.", "199 TL KDV DAHİL DEĞİLDİR"],
)
def test_turkish_kdv_dahil_degil_is_excluded_wording(text: str) -> None:
    kinds = {(p.language, p.kind) for p in markers(text).vat_phrases}
    assert ("tr", "excl") in kinds


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("€9 incl. VAT", "en"),
        ("£9 inc VAT", "en"),
        ("€9 including VAT", "en"),
        ("VAT included", "en"),
        ("€25 inclusief btw", "nl"),
        ("29 € inkl. MwSt.", "de"),
        ("Fiyatlara KDV dahildir", "tr"),
    ],
)
def test_plain_included_wording_is_still_found(text: str, language: str) -> None:
    kinds = {(p.language, p.kind) for p in markers(text).vat_phrases}
    assert (language, "incl") in kinds


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
    text = "1 " * 5_000
    started = time.monotonic()
    found = markers(text)
    elapsed = time.monotonic() - started
    assert found.currency_codes == ()
    assert elapsed < 1


@pytest.mark.parametrize("text", ["12 900 Kč", "12\u00a0900 Kč", "1.234,50 Kč", "405 Kč"])
def test_symbol_after_a_number_with_separators(text: str) -> None:
    assert markers(text).currency_symbols == ("Kč",)


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


# Free symbols count only beside a number.

FREE_SYMBOLS = ["€", "£", "¥", "₺", "₹", "₽", "₩", "$"]


def kinds(text: str, language: str | None = None) -> set[tuple[str, str]]:
    return {
        (p.language, p.kind)
        for p in markers(text).vat_phrases
        if language is None or p.language == language
    }


def test_a_currency_switcher_has_no_symbols() -> None:
    found = markers("Currency: € EUR | £ GBP | $ USD | ¥ JPY")
    assert found.currency_symbols == ()
    assert found.currency_codes == ()


@pytest.mark.parametrize("symbol", FREE_SYMBOLS)
def test_a_free_symbol_before_or_after_a_number_counts(symbol: str) -> None:
    for text in (
        f"{symbol}29",
        f"{symbol} 29",
        f"29 {symbol}",
        f"29{symbol}",
        f"Pro 1.299,50 {symbol}",
    ):
        assert markers(text).currency_symbols == (symbol,), text


@pytest.mark.parametrize("symbol", FREE_SYMBOLS)
def test_a_free_symbol_without_a_number_does_not_count(symbol: str) -> None:
    for text in (symbol, f"{symbol} per month", f"Pay in {symbol}", f"{symbol}\nno price here"):
        assert markers(text).currency_symbols == (), text


def test_the_euro_sign_and_a_number_in_a_page_that_also_lists_a_switcher() -> None:
    found = markers("€ EUR | £ GBP | $ USD\nPro €29 / month")
    assert found.currency_symbols == ("€",)


def test_a_symbol_glued_to_the_word_before_it_is_still_a_price() -> None:
    # Inline spans join without spaces: "From<span>€9</span>" reads "From€9".
    assert markers("From€9").currency_symbols == ("€",)
    assert markers("From$9").currency_symbols == ("$",)


def test_the_brazilian_real_is_not_a_dollar() -> None:
    assert markers("R$ 29").currency_symbols == ("R$",)
    assert markers("R$29,90").currency_symbols == ("R$",)
    assert markers("29 R$").currency_symbols == ("R$",)


@pytest.mark.parametrize(
    "text", ["US$ 29", "US$29", "A$ 29", "A$29", "C$5", "CA$ 5", "HK$ 5", "S$ 5", "NZ$9", "9 US$"]
)
def test_the_dollar_in_a_longer_sign_is_not_a_dollar(text: str) -> None:
    # Only R$ is a sign this module knows, so the other signs count as nothing.
    assert markers(text).currency_symbols == ()


def test_a_plain_dollar_beside_a_longer_sign_still_counts() -> None:
    assert markers("US$ 29 or $ 25").currency_symbols == ("$",)
    assert markers("R$ 29 and $29").currency_symbols == ("$", "R$")
    assert markers("US $29").currency_symbols == ("$",)
    assert markers("$29").currency_symbols == ("$",)
    assert markers("29 $").currency_symbols == ("$",)


# Company and registration-number words are not statements about prices.


@pytest.mark.parametrize(
    "text",
    [
        "Acme Inc. VAT ID: 123",
        "Acme Inc. VAT-ID DE123456789",
        "Acme Inc. VAT No. 123",
        "Acme Inc. VAT NO 123",
        "incl. VAT number GB123",
        "including VAT registration number 12",
        "excl. VAT reg. no 12",
        "Acme Inc. VAT identification number: 1",
        "Acme Inc. VAT IDs are public",
    ],
)
def test_an_english_vat_registration_line_is_no_phrase(text: str) -> None:
    assert markers(text).vat_phrases == ()


def test_inc_company_suffix_without_an_id_word_is_still_read_as_included() -> None:
    # Only the ID word is the signal; "Inc. VAT" alone stays what it was.
    assert ("en", "incl") in kinds("Acme Inc. VAT: €29")


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Prices incl. VAT no hidden fees", "incl"),  # "no" in lower case is just a word
        ("incl. VAT, ID required at checkout", "incl"),
        ("excl. VAT ideal for small teams", "excl"),
        ("incl. VAT regardless of country", "incl"),
        ("excl. VAT numbers are shown at checkout", None),
    ],
)
def test_an_ordinary_sentence_after_vat_is_still_a_phrase(text: str, kind: str | None) -> None:
    expected = set() if kind is None else {("en", kind)}
    assert kinds(text, "en") == expected


@pytest.mark.parametrize(
    "text",
    [
        "Acme B.V. incl. btw-nummer NL123",
        "excl. btw nummer NL123",
        "excl. btw nr. 12",
        "incl. btw id: 1",
        "excl. BTW-ID NL1",
    ],
)
def test_a_dutch_vat_registration_line_is_no_phrase(text: str) -> None:
    assert kinds(text, "nl") == set()


def test_dutch_btw_followed_by_an_ordinary_word_is_still_a_phrase() -> None:
    assert ("nl", "excl") in kinds("€25 excl. btw in maart")
    assert ("nl", "incl") in kinds("€25 incl. btw, nu")


@pytest.mark.parametrize(
    "text",
    [
        "Acme GmbH inkl. USt-IdNr. DE123456789",
        "inkl. MwSt-IdNr DE1",
        "zzgl. USt-ID: DE123",
        "exkl. USt IdNr. DE1",
    ],
)
def test_a_german_vat_registration_line_is_no_phrase(text: str) -> None:
    assert kinds(text, "de") == set()


def test_german_mwst_followed_by_an_ordinary_word_is_still_a_phrase() -> None:
    assert ("de", "incl") in kinds("29 € inkl. MwSt. ideal für Teams")


# More wordings.


@pytest.mark.parametrize(
    ("text", "language", "kind"),
    [
        ("€29 exclusive of VAT", "en", "excl"),
        ("€29 exclusive VAT", "en", "excl"),
        ("€29 inclusive of VAT", "en", "incl"),
        ("€29 VAT excluded", "en", "excl"),
        ("€29 plus 21% VAT", "en", "excl"),
        ("€29 plus 21 % VAT", "en", "excl"),
        ("€29 plus VAT", "en", "excl"),
        ("£29 + VAT", "en", "excl"),
        ("£29 + 20% VAT", "en", "excl"),
        ("£29 incl. 20% VAT", "en", "incl"),
        ("€25 excl. 21% btw", "nl", "excl"),
        ("€25 incl. 21% btw", "nl", "incl"),
        ("29 € zzgl. gesetzl. MwSt.", "de", "excl"),
        ("29 € zzgl. gesetzlicher MwSt.", "de", "excl"),
        ("29 € ohne MwSt.", "de", "excl"),
        ("29 € ohne 19 % MwSt.", "de", "excl"),
        ("29 € inkl. gesetzl. MwSt.", "de", "incl"),
        ("29 € inkl. 19 % gesetzl. MwSt.", "de", "incl"),
        ("24 € hors TVA", "fr", "excl"),
        ("24 € Hors TVA", "fr", "excl"),
        ("24 € TVA incluse", "fr", "incl"),
        ("22 € IVA non inclusa", "it", "excl"),
        ("22 € IVA non incl.", "it", "excl"),
        ("22 € IVA incl.", "it", "incl"),
        ("22 € IVA inclusa", "it", "incl"),
        ("199 TL KDV'si dahil", "tr", "incl"),
        ("199 TL KDV’si dahil", "tr", "incl"),
        ("199 TL KDV %20 dahil", "tr", "incl"),
        ("199 TL KDV'Sİ DAHİL", "tr", "incl"),
        ("199 TL KDV'si dahil değil", "tr", "excl"),
        ("199 TL KDV'si dahil değildir", "tr", "excl"),
        ("199 TL KDV %20 dahil değil", "tr", "excl"),
        ("199 TL KDV %20 dahil değildir", "tr", "excl"),
        ("199 TL KDV'Sİ DAHİL DEĞİL", "tr", "excl"),
        ("199 TL KDV %20 dahil degil", "tr", "excl"),
    ],
)
def test_more_vat_wordings(text: str, language: str, kind: str) -> None:
    assert (language, kind) in kinds(text)


@pytest.mark.parametrize(
    ("text", "language", "kind"),
    [
        ("22 € IVA non inclusa", "it", "incl"),
        ("22 € IVA non incl.", "it", "incl"),
        ("199 TL KDV'si dahil değil", "tr", "incl"),
        ("199 TL KDV %20 dahil değildir", "tr", "incl"),
        ("199 TL KDV'Sİ DAHİL DEĞİL", "tr", "incl"),
        ("€29 not inclusive of VAT", "en", "incl"),
        ("€29 VAT excluded", "en", "incl"),
        ("22 € IVA inclusa", "it", "excl"),
    ],
)
def test_wordings_that_must_not_read_the_other_way(text: str, language: str, kind: str) -> None:
    assert (language, kind) not in kinds(text)


def test_iva_non_inclusa_is_excluded_wording_only() -> None:
    found = [(p.language, p.kind, p.phrase) for p in markers("22 € IVA non inclusa").vat_phrases]
    assert found == [("it", "excl", "IVA non inclusa")]


# More currencies.


@pytest.mark.parametrize(
    "text", ["29 euro", "29 euros", "29 Euro", "29 EURO", "29euro", "1.299,50 euro"]
)
def test_the_word_euro_after_a_number_is_eur(text: str) -> None:
    assert markers(text).currency_codes == ("EUR",)


@pytest.mark.parametrize(
    "text", ["EURO 5", "Euro 6d emission standard", "euro 29", "Euros are accepted", "29 eurozone"]
)
def test_the_word_euro_anywhere_else_is_not_eur(text: str) -> None:
    assert markers(text).currency_codes == ()


@pytest.mark.parametrize("code", ["AED", "KRW", "SGD", "HKD"])
def test_more_currency_codes_beside_a_number(code: str) -> None:
    assert markers(f"{code} 99").currency_codes == (code,)
    assert markers(f"99 {code}").currency_codes == (code,)
    assert markers(f"Pay in {code}").currency_codes == ()


# Linear time on hostile text.


HOSTILE_TEXT = {
    "plus": "plus " * 5_000,
    "excl": "excl. " * 5_000,
    "excl-then-digits": "excl. 1" + "1" * 5_000 + ".1" * 2_000,
    "rate": "21% " * 10_000,
    "vat": "VAT " * 10_000,
    "vat-then-spaces": "incl. VAT" + " " * 50_000 + "x",
    "gesetzl": "inkl. gesetzl. " * 3_000,
    "gesetzlicher": "zzgl. " + "gesetzlicher " * 3_000,
    "kdv": "KDV " * 5_000,
    "kdv-si": "KDV'si " * 5_000,
    "kdv-percent": "KDV %" + "2" * 5_000,
    "iva-non": "IVA non " * 5_000,
    "prefixed-dollar": "US$" * 5_000,
    "spaced-dollar": "A$ " * 5_000,
    "euro-signs": "€ " * 20_000,
    "dollars": "$" * 50_000,
    "digits-then-euro": "1 " * 20_000 + "euro",
    "euros": "1 euro " * 5_000,
    "priced-euros": "€1 " * 10_000,
}


@pytest.mark.parametrize("name", HOSTILE_TEXT)
def test_new_patterns_stay_linear_on_hostile_text(name: str) -> None:
    started = time.monotonic()
    markers(HOSTILE_TEXT[name])
    assert time.monotonic() - started < 1


# One entry per phrase.


def test_a_table_repeating_one_phrase_gives_one_entry() -> None:
    found = markers("Plan: €9 excl. VAT\n" * 1_000)
    assert [(p.language, p.kind, p.phrase) for p in found.vat_phrases] == [
        ("en", "excl", "excl. VAT")
    ]


def test_phrases_are_kept_once_each_in_the_order_they_were_found() -> None:
    text = "Basic incl. VAT. Pro excl. VAT. Team incl. VAT. Max Excl. VAT. Plus excl. VAT."
    found = [(p.language, p.kind, p.phrase) for p in markers(text).vat_phrases]
    assert found == [
        ("en", "excl", "excl. VAT"),
        ("en", "excl", "Excl. VAT"),
        ("en", "incl", "incl. VAT"),
    ]


def test_the_same_wording_in_two_languages_is_two_entries() -> None:
    found = [(p.language, p.kind, p.phrase) for p in markers("+ IVA + IVA").vat_phrases]
    assert found == [("es", "excl", "+ IVA"), ("it", "excl", "+ IVA")]


# Language signals are trimmed.


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("<html lang=' nl-NL '>", "nl-NL"),
        ("<html lang='\tde\n'>", "de"),
        ("<html lang=''>", None),
        ("<html lang='   '>", None),
        ("<html>", None),
        ("<p>no root</p>", None),
    ],
)
def test_html_lang_is_trimmed_and_empty_is_none(html: str, expected: str | None) -> None:
    assert markers("x", html=html).html_lang == expected


@pytest.mark.parametrize(
    ("value", "expected"), [(" nl ", "nl"), ("nl-NL, en", "nl-NL, en"), ("", None), ("  \t", None)]
)
def test_content_language_is_trimmed_and_empty_is_none(value: str, expected: str | None) -> None:
    assert markers("x", headers={"Content-Language": value}).content_language == expected


def test_no_content_language_header_is_none() -> None:
    assert markers("x", headers={"Content-Type": "text/html"}).content_language is None


# Boundaries: a code or sign that is part of a longer word is not one.


def test_ht_in_a_product_name_is_not_a_french_phrase() -> None:
    assert kinds("The HT-Series mixer", "fr") == set()
    assert kinds("HT_pro", "fr") == set()
    assert kinds("29 € HT", "fr") == {("fr", "excl")}


def test_a_czech_crown_followed_by_a_letter_is_not_czk() -> None:
    found = markers("405 Kčx")
    assert found.currency_symbols == ()
    assert found.currency_codes == ()
    assert markers("405 Kč").currency_symbols == ("Kč",)


def test_euro_5_is_not_eur() -> None:
    assert markers("EURO 5").currency_codes == ()
    assert markers("EUR 5").currency_codes == ("EUR",)
