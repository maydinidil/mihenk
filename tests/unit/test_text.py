from mihenk.trim.text import canonical_text, html_to_text


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
