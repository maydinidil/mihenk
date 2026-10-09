from mihenk.capture.fetch import decode_html
from tests.helpers.pages import PAGES_DIR, load_expectations

TURKISH = "<meta charset='windows-1254'><p>Aylık 199 TL, Fiyatlara KDV dahildir. İstanbul şube</p>"


def test_header_charset_wins() -> None:
    text, encoding = decode_html("€29".encode(), "text/html; charset=utf-8")
    assert (text, encoding) == ("€29", "utf-8")


def test_decode_windows_1254_from_meta() -> None:
    text, encoding = decode_html(TURKISH.encode("cp1254"), "text/html")
    assert encoding == "cp1254"
    assert "Aylık 199 TL" in text
    assert "İstanbul şube" in text


def test_utf8_bom() -> None:
    text, encoding = decode_html(b"\xef\xbb\xbf<p>\xe2\x82\xac9</p>", None)
    assert text == "<p>€9</p>"
    assert encoding == "utf-8-sig"


def test_unknown_charset_falls_back_to_utf8() -> None:
    text, encoding = decode_html("€9".encode(), "text/html; charset=no-such-thing")
    assert (text, encoding) == ("€9", "utf-8")


def test_header_charset_beats_meta() -> None:
    body = "<meta charset='utf-8'><p>Aylık</p>".encode("cp1254")
    text, encoding = decode_html(body, "text/html; charset=windows-1254")
    assert encoding == "cp1254"
    assert "Aylık" in text


def test_quoted_header_charset() -> None:
    text, encoding = decode_html("İstanbul".encode("cp1254"), 'text/html; charset="windows-1254"')
    assert (text, encoding) == ("İstanbul", "cp1254")


def test_meta_http_equiv_charset() -> None:
    page = "<meta http-equiv='Content-Type' content='text/html; charset=windows-1254'>şube"
    text, encoding = decode_html(page.encode("cp1254"), None)
    assert encoding == "cp1254"
    assert text.endswith("şube")


def test_undecodable_bytes_are_replaced_not_raised() -> None:
    text, encoding = decode_html(b"<p>\xff\xfe9</p>", "text/html; charset=utf-8")
    assert encoding == "utf-8"
    assert text.startswith("<p>") and text.endswith("9</p>")
    assert "�" in text


def test_a_declared_charset_that_is_not_a_text_encoding_falls_back_to_utf8() -> None:
    # `codecs.lookup` finds these names, but they cannot turn bytes into text.
    for name in ("hex", "base64", "rot13", "undefined"):
        text, encoding = decode_html("€9".encode(), f"text/html; charset={name}")
        assert (text, encoding) == ("€9", "utf-8"), name
        page = f"<meta charset='{name}'><p>€9</p>".encode()
        text, encoding = decode_html(page, "text/html")
        assert (text, encoding) == (page.decode("utf-8"), "utf-8"), name


def test_empty_body() -> None:
    assert decode_html(b"", None) == ("", "utf-8")


# Browsers read these labels as Windows code pages (WHATWG), and pages depend on it.

# Curly quotes, an en dash (U+2013), the euro sign and an ellipsis: all in windows-1252 only.
EN_DASH, LEFT_QUOTE = chr(0x2013), chr(0x2018)
CP1252_TEXT = f"Plan “Pro” {EN_DASH} €29, {LEFT_QUOTE}ek’ …"
LATIN1_LABELS = ("iso-8859-1", "ISO-8859-1", "iso_8859-1", "latin1", "latin-1", "l1", "cp819")
ASCII_LABELS = ("us-ascii", "ascii", "iso-ir-6", "ansi_x3.4-1968")
LATIN5_LABELS = ("iso-8859-9", "latin5", "l5", "iso8859-9", "iso_8859-9")


def test_latin1_and_ascii_labels_in_the_header_are_read_as_windows_1252() -> None:
    body = CP1252_TEXT.encode("cp1252")
    for label in (*LATIN1_LABELS, *ASCII_LABELS):
        text, encoding = decode_html(body, f"text/html; charset={label}")
        assert (text, encoding) == (CP1252_TEXT, "cp1252"), label


def test_latin1_and_ascii_labels_in_a_meta_tag_are_read_as_windows_1252() -> None:
    for label in (*LATIN1_LABELS, *ASCII_LABELS):
        page = f"<meta charset={label}><p>{CP1252_TEXT}</p>".encode("cp1252")
        text, encoding = decode_html(page, "text/html")
        assert text.endswith(f"<p>{CP1252_TEXT}</p>"), label
        assert encoding == "cp1252", label
        page = f"<meta http-equiv='Content-Type' content='text/html; charset={label}'>€9"
        text, encoding = decode_html(page.encode("cp1252"), None)
        assert text.endswith("€9"), label
        assert encoding == "cp1252", label


def test_latin5_labels_are_read_as_windows_1254() -> None:
    turkish = "Aylık €199, İstanbul şube, Fiyatlara KDV dahildir"
    body = turkish.encode("cp1254")
    for label in LATIN5_LABELS:
        text, encoding = decode_html(body, f"text/html; charset={label}")
        assert (text, encoding) == (turkish, "cp1254"), label
        page = f"<meta charset={label}>{turkish}".encode("cp1254")
        text, encoding = decode_html(page, "text/html")
        assert text.endswith(turkish), label
        assert encoding == "cp1254", label


def test_other_iso_labels_are_not_remapped() -> None:
    polish = "Zażółć gęślą jaźń"
    text, encoding = decode_html(polish.encode("iso8859-2"), "text/html; charset=iso-8859-2")
    assert (text, encoding) == (polish, "iso8859-2")


def test_the_windows_1254_trap_page_still_decodes() -> None:
    body = (PAGES_DIR / "windows-1254" / "page.html").read_bytes()
    text, encoding = decode_html(body, "text/html")
    assert encoding == "cp1254"
    for expected in load_expectations("windows-1254")["fetch_text_contains"]:
        assert expected in text
