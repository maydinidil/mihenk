import socket
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from mihenk.app.launcher import bind_loopback, launch_url, new_token
from mihenk.app.paths import logs_dir


def test_bind_loopback_gives_a_free_local_port() -> None:
    sock = bind_loopback()
    try:
        host, port = sock.getsockname()[:2]
        assert host == "127.0.0.1"
        assert port > 0
        assert sock.family == socket.AF_INET
    finally:
        sock.close()


def test_tokens_are_long_unique_and_url_safe() -> None:
    tokens = {new_token() for _ in range(20)}
    assert len(tokens) == 20
    assert all(len(t) >= 40 and t.isascii() for t in tokens)
    assert all(
        set(t) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
        for t in tokens
    )


def test_launch_url_keeps_the_token_in_the_fragment() -> None:
    assert launch_url(5000, "abc") == "http://127.0.0.1:5000/#token=abc"
    assert launch_url(5000, "abc", smoke=True) == "http://127.0.0.1:5000/#token=abc&smoke=1"


def test_launch_url_fragment_round_trips_like_the_screens_parse_it() -> None:
    # web/src/api/client.ts reads location.hash with URLSearchParams; parse_qs is the same
    # grammar. Any token new_token() makes must come back byte for byte.
    for _ in range(50):
        token = new_token()
        fragment = urlsplit(launch_url(5000, token)).fragment
        assert parse_qs(fragment, strict_parsing=True) == {"token": [token]}
        smoke_fragment = urlsplit(launch_url(5000, token, smoke=True)).fragment
        assert parse_qs(smoke_fragment, strict_parsing=True) == {"token": [token], "smoke": ["1"]}


def test_data_dir_override_with_spaces_and_turkish_letters(tmp_path: Path) -> None:
    data_dir = tmp_path / "Ayşe Yılmaz" / "mihenk data"
    logs = logs_dir(data_dir)
    assert logs.is_dir()
    (logs / "probe.txt").write_text("şğıİ", encoding="utf-8")
    assert (logs / "probe.txt").read_text(encoding="utf-8") == "şğıİ"
