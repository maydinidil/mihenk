import random

import pytest

from mihenk.trim.text import canonical_text, html_to_text, scrub_surrogates


def test_canonical_text_collapses_spaces_and_keeps_line_breaks() -> None:
    raw = "Pro\u00a0plan  \t €\u202f49 \r\n\r\n\r\n\r\nper month\u200b"
    assert canonical_text(raw) == "Pro plan € 49\n\nper month\n"


def test_canonical_text_is_nfc_and_keeps_turkish_and_minus_sign() -> None:
    decomposed = "I\u0307stanbul \u22125%"
    assert canonical_text(decomposed) == "İstanbul −5%\n"


def test_inline_spans_join_without_spaces() -> None:
    html = "<p>Price: <span>€</span><span>4</span><span>9</span></p>"
    assert html_to_text(html) == "Price: €49\n"


def test_blocks_become_lines_and_scripts_are_dropped() -> None:
    html = "<div>Basic</div><div>€9 / month</div><script>var x = 405;</script><style>p{}</style>"
    assert html_to_text(html) == "Basic\n€9 / month\n"


def test_source_newlines_inside_text_are_spaces() -> None:
    assert html_to_text("<p>billed\n   yearly</p>") == "billed yearly\n"


def test_svg_path_numbers_do_not_appear() -> None:
    html = '<svg><path d="M405 10 L405 20"/></svg><p>405 Kč</p>'
    assert html_to_text(html) == "405 Kč\n"


def test_hidden_elements_are_dropped() -> None:
    assert html_to_text("<p hidden>€99</p><p>€9</p>") == "€9\n"


def test_a_page_without_a_closing_head_tag_keeps_its_body_text() -> None:
    # html.parser never closes an open <head>, so the body nests inside it.
    assert html_to_text("<html><head><title>T</title><body><p>€9</p>") == "€9\n"


def test_deeply_nested_elements_do_not_exhaust_the_stack() -> None:
    html = "<div>" * 5_000 + "€9" + "</div>" * 5_000
    assert html_to_text(html) == "€9\n"


def test_thousands_of_unclosed_list_items_do_not_exhaust_the_stack() -> None:
    # html.parser never closes an <li>, so every item nests inside the one before it.
    html = "<ul>" + "<li>€9" * 5_000 + "</ul>"
    assert html_to_text(html) == "€9\n" * 5_000


E_ACUTE = "\N{LATIN SMALL LETTER E WITH ACUTE}"
ZWSP = "\N{ZERO WIDTH SPACE}"
BOM = "\N{ZERO WIDTH NO-BREAK SPACE}"
ACUTE = "\N{COMBINING ACUTE ACCENT}"
DOT_ABOVE = "\N{COMBINING DOT ABOVE}"


@pytest.mark.parametrize(
    "raw",
    [
        f"e{ZWSP}{ACUTE}",  # an invisible character between a letter and its accent
        f"e{BOM}{ACUTE}",
        f"I{ZWSP}{DOT_ABOVE}stanbul",
        f"{ZWSP}e{ZWSP}{ZWSP}{ACUTE}{BOM}",
        "\N{HANGUL CHOSEONG KIYEOK}" + ZWSP + "\N{HANGUL JUNGSEONG A}",
        "a\r\n\r\n\r\n\r\nb\r",
        f"Pro\N{NO-BREAK SPACE}plan  \t \N{EURO SIGN}\N{NARROW NO-BREAK SPACE}49 \r\n{ZWSP}\n\n\nx",
        f" {ZWSP} \n {BOM} \n",
        "\N{EN QUAD}\N{COMBINING ACUTE ACCENT}",
        "\N{ANGSTROM SIGN}\N{COMBINING DOT BELOW}",
        "",
    ],
)
def test_canonical_text_is_idempotent(raw: str) -> None:
    once = canonical_text(raw)
    assert canonical_text(once) == once


def test_invisible_characters_are_removed_before_the_accent_is_composed() -> None:
    assert canonical_text(f"e{ZWSP}{ACUTE}") == f"{E_ACUTE}\n"
    assert canonical_text(f"e{BOM}{ACUTE}") == f"{E_ACUTE}\n"
    assert (
        canonical_text(f"I{ZWSP}{DOT_ABOVE}stanbul")
        == "\N{LATIN CAPITAL LETTER I WITH DOT ABOVE}stanbul\n"
    )


def test_canonical_text_is_idempotent_on_mixed_noise() -> None:
    # A seeded run over the characters that interact: accents, invisible characters, spaces and
    # every kind of line break.
    alphabet = [
        "e",
        "I",
        "a",
        "\N{COMBINING ACUTE ACCENT}",
        "\N{COMBINING DOT ABOVE}",
        "\N{COMBINING DOT BELOW}",
        "\N{ZERO WIDTH SPACE}",
        "\N{ZERO WIDTH NO-BREAK SPACE}",
        "\N{NO-BREAK SPACE}",
        "\N{EN QUAD}",
        "\N{ANGSTROM SIGN}",
        "\N{HANGUL CHOSEONG KIYEOK}",
        "\N{HANGUL JUNGSEONG A}",
        " ",
        "\t",
        "\n",
        "\r",
        "\r\n",
        "\N{LINE SEPARATOR}",
    ]
    rng = random.Random(20261008)  # noqa: S311 - a seeded test generator, not security
    for _ in range(3000):
        raw = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))
        once = canonical_text(raw)
        assert canonical_text(once) == once, repr(raw)


# Lone surrogates.


def test_a_lone_surrogate_becomes_a_replacement_character() -> None:
    high, low = chr(0xD83D), chr(0xDC00)
    assert scrub_surrogates(f"price {high} 9") == "price \N{REPLACEMENT CHARACTER} 9"
    assert (
        scrub_surrogates(f"{low}x{high}") == "\N{REPLACEMENT CHARACTER}x\N{REPLACEMENT CHARACTER}"
    )


def test_the_two_halves_of_a_pair_split_across_two_characters_are_each_replaced() -> None:
    # In a Python string they are two code points, not the one emoji they would spell in UTF-16.
    text = scrub_surrogates("a" + chr(0xD83D) + chr(0xDE00) + "b")
    assert text == "a\N{REPLACEMENT CHARACTER}\N{REPLACEMENT CHARACTER}b"
    text.encode("utf-8")


def test_text_without_surrogates_is_returned_as_it_is() -> None:
    emoji = chr(0x1F600)
    text = f"Aylık \N{EURO SIGN}9 {emoji} \N{LATIN CAPITAL LETTER I WITH DOT ABOVE}stanbul"
    assert scrub_surrogates(text) == text
    assert scrub_surrogates("") == ""


# Form controls read one value per line.


def test_the_options_of_a_select_are_separate_lines() -> None:
    html = "<select><option>EUR</option><option>USD</option></select>"
    assert html_to_text(html) == "EUR\nUSD\n"


def test_optgroups_and_their_options_are_separate_lines() -> None:
    html = (
        "<select><optgroup label='Europe'><option>EUR</option><option>GBP</option></optgroup>"
        "<optgroup label='Asia'><option>JPY</option></optgroup></select>"
    )
    assert html_to_text(html) == "EUR\nGBP\nJPY\n"


def test_a_legend_is_its_own_line() -> None:
    html = "<fieldset><legend>Billing</legend>Monthly</fieldset>"
    assert html_to_text(html) == "Billing\nMonthly\n"


def test_a_select_inside_a_sentence_does_not_glue_its_options_to_the_words_around_it() -> None:
    html = "<p>Currency: <select><option>EUR</option><option>USD</option></select> per month</p>"
    assert html_to_text(html) == "Currency:\nEUR\nUSD\nper month\n"


def test_br_is_still_a_line_break() -> None:
    assert html_to_text("Line one<br>Line two<br/>Line three") == "Line one\nLine two\nLine three\n"
