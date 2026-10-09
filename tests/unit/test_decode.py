import codecs

import pytest

from mihenk.capture.fetch import _ALLOWED_CODECS, decode_html
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


# UTF-16: a byte order mark is read like the UTF-8 one (WHATWG Encoding Standard).

EURO_PLAN = "€29 Pro-Plan, Aylık İstanbul"


def test_utf16_little_endian_bom() -> None:
    body = codecs.BOM_UTF16_LE + EURO_PLAN.encode("utf-16-le")
    assert decode_html(body, None) == (EURO_PLAN, "utf-16-le")


def test_utf16_big_endian_bom() -> None:
    body = codecs.BOM_UTF16_BE + EURO_PLAN.encode("utf-16-be")
    assert decode_html(body, None) == (EURO_PLAN, "utf-16-be")


def test_a_utf16_bom_beats_the_http_header_and_the_meta_tag() -> None:
    body = codecs.BOM_UTF16_LE + "<meta charset='windows-1254'>€9".encode("utf-16-le")
    assert decode_html(body, "text/html; charset=utf-8") == (
        "<meta charset='windows-1254'>€9",
        "utf-16-le",
    )


def test_a_utf16_bom_with_a_truncated_last_unit_is_replaced_not_raised() -> None:
    body = codecs.BOM_UTF16_LE + "€9".encode("utf-16-le") + b"A"
    assert decode_html(body, None) == ("€9\N{REPLACEMENT CHARACTER}", "utf-16-le")


def test_the_utf8_bom_still_wins_first() -> None:
    assert decode_html(codecs.BOM_UTF8 + "€9".encode(), "text/html; charset=utf-16") == (
        "€9",
        "utf-8-sig",
    )


@pytest.mark.parametrize(
    ("label", "encoding"),
    [("utf-16", "utf-16-le"), ("UTF-16LE", "utf-16-le"), ("utf-16be", "utf-16-be")],
)
def test_a_utf16_label_in_the_http_header_is_honoured(label: str, encoding: str) -> None:
    body = EURO_PLAN.encode(encoding)  # no BOM
    assert decode_html(body, f"text/html; charset={label}") == (EURO_PLAN, encoding)


@pytest.mark.parametrize("label", ["utf-16", "utf-16le", "utf-16be", "UTF-16"])
def test_a_utf16_label_in_a_meta_tag_is_read_as_utf8(label: str) -> None:
    # The tag was found by reading the bytes as ASCII, so the page cannot be UTF-16.
    page = f"<meta charset={label}><p>{EURO_PLAN}</p>".encode()
    text, encoding = decode_html(page, "text/html")
    assert encoding == "utf-8"
    assert text.endswith(f"<p>{EURO_PLAN}</p>")
    page = f"<meta http-equiv='Content-Type' content='text/html; charset={label}'>{EURO_PLAN}"
    assert decode_html(page.encode(), None)[1] == "utf-8"


# A charset in single quotes in the header.


def test_single_quoted_header_charset() -> None:
    text, encoding = decode_html("İstanbul".encode("cp1254"), "text/html; charset='windows-1254'")
    assert (text, encoding) == ("İstanbul", "cp1254")


# Only the encodings of the WHATWG table are used.

ALLOWED_LABELS = [
    ("windows-1250", "Zażółć gęślą jaźń", "cp1250"),
    ("windows-1251", "Привет, мир €", "cp1251"),
    ("windows-1252", "Plan “Pro” €29", "cp1252"),
    ("windows-1253", "Καλημέρα κόσμε", "cp1253"),
    ("windows-1254", "Aylık İstanbul şube", "cp1254"),
    ("windows-1255", "שלום עולם", "cp1255"),
    ("windows-1256", "مرحبا بالعالم", "cp1256"),
    ("windows-1257", "Žemė ir dangus", "cp1257"),
    ("windows-1258", "Xin chào", "cp1258"),
    ("iso-8859-2", "Zażółć gęślą", "iso8859-2"),
    ("iso-8859-3", "Ħaġar", "iso8859-3"),
    ("iso-8859-4", "Ķemeri", "iso8859-4"),
    ("iso-8859-5", "Привет", "iso8859-5"),
    ("iso-8859-6", "مرحبا", "iso8859-6"),
    ("iso-8859-7", "Καλημέρα", "iso8859-7"),
    ("iso-8859-8", "שלום", "iso8859-8"),
    ("iso-8859-10", "Ísland Þór", "iso8859-10"),
    ("iso-8859-13", "Žemė", "iso8859-13"),
    ("iso-8859-14", "Ŵŷ", "iso8859-14"),
    ("iso-8859-15", "€ Œuvre", "iso8859-15"),
    ("iso-8859-16", "Brașov", "iso8859-16"),
    ("koi8-r", "Привет", "koi8-r"),
    ("koi8-u", "Привіт", "koi8-u"),
    ("ibm866", "Привет", "cp866"),
    ("cp874", "สวัสดี", "cp874"),
    ("macintosh", "café", "mac-roman"),
    ("mac-cyrillic", "Привет", "mac-cyrillic"),
    ("gbk", "你好世界", "gbk"),
    ("gb18030", "你好世界", "gb18030"),
    ("big5", "你好世界", "big5"),
    ("big5-hkscs", "你好世界", "big5hkscs"),
    ("euc-jp", "こんにちは", "euc_jp"),
    ("iso-2022-jp", "こんにちは", "iso2022_jp"),
    ("shift_jis", "こんにちは", "shift_jis"),
    ("cp932", "こんにちは", "cp932"),
    ("euc-kr", "안녕하세요", "euc_kr"),
    ("cp949", "안녕하세요", "cp949"),
    # Labels that browsers read as a wider encoding than Python's codec of that name.
    ("gb2312", "你好世界", "gbk"),
    ("tis-620", "สวัสดี", "cp874"),
    ("iso-8859-11", "สวัสดี", "cp874"),
]


@pytest.mark.parametrize(("label", "sample", "encoding"), ALLOWED_LABELS)
def test_an_encoding_of_the_whatwg_table_is_used(label: str, sample: str, encoding: str) -> None:
    body = sample.encode(encoding)
    assert decode_html(body, f"text/html; charset={label}") == (sample, encoding)
    tag = f"<meta charset='{label}'>"
    text, used = decode_html(tag.encode("ascii") + body, None)
    assert (text.removeprefix(tag), used) == (sample, encoding)


REFUSED = [
    "utf-7",  # a text encoding, but one no browser reads
    "utf-32",
    "utf-32-le",
    "utf-8-sig",
    "unicode_escape",
    "raw_unicode_escape",
    "punycode",
    "idna",
    "mbcs",
    "oem",
    "rot13",
    "hex",
    "base64",
    "zlib",
    "bz2",
    "uu",
    "quopri",
    "undefined",
    "cp437",  # legacy code pages that are not in the table
    "cp850",
    "cp037",
    "hz",
    "no-such-thing",
]


@pytest.mark.parametrize("name", REFUSED)
def test_an_encoding_outside_the_whatwg_table_is_ignored(name: str) -> None:
    # Ignored means: as if the page had declared nothing, so the next candidate is tried.
    assert decode_html("€9".encode(), f"text/html; charset={name}") == ("€9", "utf-8")
    page = f"<meta charset='{name}'><p>€9</p>".encode()
    assert decode_html(page, "text/html") == (page.decode("utf-8"), "utf-8")
    # A refused header charset does not stop a valid <meta> after it from being read.
    turkish = "<meta charset='windows-1254'>İstanbul".encode("cp1254")
    assert decode_html(turkish, f"text/html; charset={name}")[1] == "cp1254"


def test_a_refused_encoding_does_not_change_plain_text() -> None:
    # utf-7 would turn "+AOk-" into "é"; the page is really UTF-8, so it stays as written.
    text, encoding = decode_html(b"<p>caf\xc3\xa9 +AOk-</p>", "text/html; charset=utf-7")
    assert (text, encoding) == ("<p>café +AOk-</p>", "utf-8")


def test_every_allowed_encoding_decodes_any_bytes_without_raising() -> None:
    noise = bytes(range(256)) * 4 + b"\xff\xfe\x00\xd8"
    for name in sorted(_ALLOWED_CODECS):
        text, encoding = decode_html(noise, f"text/html; charset={name}")
        assert encoding == name
        assert isinstance(text, str)


# The <meta> prescan: the first 1024 bytes, without comments.


def test_a_meta_tag_inside_the_first_1024_bytes_is_read() -> None:
    padding = b"<!-- " + b"x" * 900 + b" -->"
    page = padding + b"<meta charset='windows-1254'>" + "İstanbul".encode("cp1254")
    assert len(page) < 1024
    assert decode_html(page, None)[1] == "cp1254"


def test_a_meta_tag_after_the_first_1024_bytes_is_not_read_for_a_page_that_is_utf8() -> None:
    padding = b"<p>" + b"x" * 1100 + b"</p>"
    page = padding + b"<meta charset='windows-1254'>" + "İstanbul".encode()
    assert decode_html(page, None) == (page.decode("utf-8"), "utf-8")


def test_a_meta_tag_cut_by_the_1024_byte_window_is_not_read() -> None:
    # The window ends after `big5`, which is itself a charset: the cut must not pass for one.
    tag = b"<meta charset='big5-hkscs'>"
    page = b"<p>" + b"x" * (1024 - len(b"<p>") - len(b"<meta charset='big5")) + tag
    assert page[:1024].endswith(b"charset='big5")
    assert decode_html(page, None)[1] == "utf-8"
    # The same tag, whole inside the window, is read.
    page = b"<p>" + b"x" * (1024 - len(b"<p>") - len(tag)) + tag + b"<p>x</p>"
    assert decode_html(page, None)[1] == "big5hkscs"


def test_a_short_page_whose_meta_value_ends_the_body_is_still_read() -> None:
    assert decode_html(b"<meta charset=windows-1254", None)[1] == "cp1254"


def test_a_meta_tag_in_a_comment_is_not_read() -> None:
    page = b"<!-- <meta charset='windows-1254'> --><meta charset='utf-8'><p>\xe2\x82\xac9</p>"
    assert decode_html(page, None) == (page.decode("utf-8"), "utf-8")


def test_a_meta_tag_after_a_comment_is_read() -> None:
    page = b"<!-- <meta charset='utf-8'> --><meta charset='windows-1254'>"
    assert decode_html(page + "İstanbul".encode("cp1254"), None)[1] == "cp1254"


def test_a_comment_that_is_never_closed_hides_the_rest_of_the_window() -> None:
    page = b"<!-- <meta charset='windows-1254'>" + "İstanbul".encode("cp1254")
    assert decode_html(page, None)[1] == "utf-8"


def test_several_comments_each_end_at_their_own_close() -> None:
    page = (
        b"<!-- a --><!-- <meta charset='utf-8'> -->"
        b"<meta charset='windows-1254'><!-- b -->" + "İstanbul".encode("cp1254")
    )
    assert decode_html(page, None)[1] == "cp1254"


def test_the_header_charset_is_not_limited_by_the_prescan_window() -> None:
    page = b"<p>" + b"x" * 2000 + "</p>İstanbul".encode("cp1254")
    assert decode_html(page, "text/html; charset=windows-1254")[1] == "cp1254"


# The late <meta>: a second look, only for a page with no declared charset that is not UTF-8.

LETTERS = "ışık şeker ğ"


def _late_page(body: bytes, meta: bytes = b'<meta charset="windows-1254">') -> bytes:
    """A page whose <meta charset> comes at byte 1424, after a script, inside the head."""
    script = b'<script>var padding = "' + b"p" * 1347 + b'";</script>'
    page = b"<!doctype html><html><head><title>t</title>" + script + meta
    page += b"</head><body><p>" + body + b"</p></body></html>"
    assert page.index(meta) >= 1024
    return page


def test_a_late_meta_tag_reads_a_windows_1254_page_with_no_header_charset() -> None:
    page = _late_page(LETTERS.encode("cp1254"))
    assert page.index(b"<meta") == 1424  # past the 1024-byte prescan
    text, encoding = decode_html(page, "text/html")
    assert encoding == "cp1254"
    assert LETTERS in text
    assert "\ufffd" not in text


def test_a_late_meta_tag_is_read_with_no_content_type_at_all() -> None:
    assert decode_html(_late_page(LETTERS.encode("cp1254")), None)[1] == "cp1254"


def test_a_utf8_page_with_a_late_wrong_meta_tag_stays_utf8() -> None:
    page = _late_page(LETTERS.encode("utf-8"))  # the meta says windows-1254, the bytes are UTF-8
    text, encoding = decode_html(page, "text/html")
    assert encoding == "utf-8"
    assert LETTERS in text
    assert "\ufffd" not in text


def test_the_first_1024_bytes_still_come_first() -> None:
    early = b'<meta charset="windows-1254">'
    page = early + _late_page(LETTERS.encode("cp1254"), meta=b'<meta charset="utf-8">')
    assert decode_html(page, None)[1] == "cp1254"


def test_a_header_charset_beats_a_late_meta_tag() -> None:
    page = _late_page(LETTERS.encode("cp1254"), meta=b'<meta charset="utf-8">')
    text, encoding = decode_html(page, "text/html; charset=windows-1254")
    assert (encoding, LETTERS in text) == ("cp1254", True)


def test_a_header_charset_that_is_not_usable_does_not_stop_the_late_meta_tag() -> None:
    page = _late_page(LETTERS.encode("cp1254"))
    assert decode_html(page, "text/html; charset=no-such-thing")[1] == "cp1254"


def test_a_late_meta_tag_in_a_comment_is_not_read() -> None:
    page = _late_page(
        LETTERS.encode("cp1254"),
        meta=b'<!-- <meta charset="windows-1254"> --><meta charset="utf-8">',
    )
    assert decode_html(page, None)[1] == "utf-8"


def test_a_meta_tag_after_the_head_is_not_read() -> None:
    script = b'<script>var padding = "' + b"p" * 1347 + b'";</script>'
    page = b"<html><head>" + script + b"</head><body>" + LETTERS.encode("cp1254")
    page += b'<meta charset="windows-1254"></body></html>'
    text, encoding = decode_html(page, None)
    assert encoding == "utf-8"
    assert "\ufffd" in text


def test_a_late_meta_tag_with_a_charset_outside_the_table_is_ignored() -> None:
    page = _late_page(LETTERS.encode("cp1254"), meta=b'<meta charset="utf-7">')
    assert decode_html(page, None)[1] == "utf-8"


def test_a_late_meta_tag_that_says_utf16_is_read_as_utf8() -> None:
    page = _late_page(LETTERS.encode("cp1254"), meta=b'<meta charset="utf-16le">')
    assert decode_html(page, None)[1] == "utf-8"


def test_a_late_meta_tag_past_64_kib_is_not_read() -> None:
    padding = b'<script>var padding = "' + b"p" * (64 * 1024) + b'";</script>'
    page = b"<html><head>" + padding + b'<meta charset="windows-1254"></head><body>'
    page += LETTERS.encode("cp1254") + b"</body></html>"
    assert decode_html(page, None)[1] == "utf-8"


def test_a_late_meta_value_cut_by_the_64_kib_limit_is_not_read() -> None:
    tag = b"<meta charset='big5-hkscs'>"
    padding = b"<html><head><p>" + b"x" * (
        64 * 1024 - len(b"<html><head><p>") - len(b"<meta charset='big5")
    )
    page = padding + tag + LETTERS.encode("cp1254")
    assert page[: 64 * 1024].endswith(b"charset='big5")
    assert decode_html(page, None)[1] == "utf-8"


def test_a_page_that_is_not_utf8_and_declares_nothing_is_decoded_as_before() -> None:
    page = b"<html><head><title>t</title></head><body>" + LETTERS.encode("cp1254")
    text, encoding = decode_html(page, None)
    assert encoding == "utf-8"
    assert "\ufffd" in text
