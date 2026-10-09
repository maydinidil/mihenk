from mihenk.capture.fetch import decode_html

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
