"""The command line's pure parts and its refusals. Nothing here reaches a web page."""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

from mihenk import cli
from mihenk.capture.models import SAFE_SEGMENT

# --- the region of a locale name ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "region"),
    [
        ("en_NL", "NL"),
        ("en-NL", "NL"),
        ("nl-nl", "NL"),
        ("tr_TR.UTF-8", "TR"),
        ("en_US@euro", "US"),
        ("zh-Hans-CN", "CN"),  # Windows names can carry a script
        ("sr-Latn-RS", "RS"),
        # Windows' locale.getlocale() gives a long English name: the country spelled out is not
        # a region, and must not turn into "NETHERLANDS".
        ("English_Netherlands", "ZZ"),
        ("English_United States.1252", "ZZ"),
        ("Turkish_Türkiye.1254", "ZZ"),
        ("C", "ZZ"),
        ("POSIX", "ZZ"),
        ("en", "ZZ"),
        ("es-419", "ZZ"),
        ("zh-Hant", "ZZ"),
        ("en-N1", "ZZ"),
        ("en-ŞŞ", "ZZ"),
        ("", "ZZ"),
        (None, "ZZ"),
    ],
)
def test_region_from_locale(name: str | None, region: str) -> None:
    assert cli.region_from_locale(name) == region


def test_the_system_locale_gives_a_two_letter_region_or_unknown() -> None:
    name = cli.system_locale_name()
    assert name is None or isinstance(name, str)
    assert re.fullmatch("[A-Z]{2}", cli.region_from_locale(name))


# --- the default page key -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "key"),
    [
        ("http://127.0.0.1:5000/static-table", "127-0-0-1-static-table"),
        ("https://www.Example.com/en/Pricing/?plan=1#top", "www-example-com-en-pricing"),
        ("https://example.com", "example-com"),
        ("https://example.com:8443/", "example-com"),  # no port in the key
        ("https://bücher.example/preise", "xn-bcher-kva-example-preise"),
        ("http://nul/", "page-nul"),  # a name Windows reserves for a device
        ("http://[::1/x", "page"),  # not a URL; the capture refuses it later
        ("", "page"),
    ],
)
def test_default_key(url: str, key: str) -> None:
    assert cli.default_key(url) == key
    assert SAFE_SEGMENT.fullmatch(key)


def test_default_key_is_at_most_64_characters_and_never_ends_in_a_dash() -> None:
    key = cli.default_key("https://example.com/" + "pricing/" * 30)
    assert len(key) <= 64
    assert not key.endswith("-")
    assert SAFE_SEGMENT.fullmatch(key)
    # 63 characters of host, a dash, then the path: the cut falls on the dash.
    edge = cli.default_key("https://" + "a" * 63 + ".example/x")
    assert len(edge) <= 64
    assert not edge.endswith("-")
    assert SAFE_SEGMENT.fullmatch(edge)


# --- command lines the command refuses (exit 2, before anything is requested) -------------------


def _refused(
    argv: list[str], capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> tuple[int, str]:
    code = cli.main([*argv, "--data-dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert captured.out == ""
    assert list(tmp_path.iterdir()) == []
    return code, captured.err


def test_no_command_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 2
    assert "usage" in capsys.readouterr().err


def test_help_exits_zero_and_describes_the_options(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["capture", "--help"]) == 0
    text = " ".join(capsys.readouterr().out.split())
    for option in ("--key", "--method", "--state", "--ignore-robots", "--country", "--data-dir"):
        assert option in text


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["capture", "http://127.0.0.1/x", "--key", "Not Safe"], "a key is 1 to 64"),
        (["capture", "http://127.0.0.1/x", "--key", "nul"], "a key is 1 to 64"),
        (["capture", "http://127.0.0.1/x", "--country", "NLD"], "a country is two letters"),
        (["capture", "http://127.0.0.1/x", "--country", "N1"], "a country is two letters"),
        (["capture", "http://127.0.0.1/x", "--method", "scrape"], "invalid choice"),
        (["capture"], "the following arguments are required"),
    ],
)
def test_bad_options_are_refused_with_exit_2(
    argv: list[str], message: str, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code, err = _refused(argv, capsys, tmp_path)
    assert code == 2
    assert message in err


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        # State labels are folder names.
        (["--state", "Monthly=Monthly"], "unsafe state label"),
        (["--state", "a b"], "unsafe state label"),
        (["--state", "monthly="], "at least 1 character"),
        # A fetch or render recipe is one state with no actions.
        (["--method", "fetch", "--state", "monthly=Monthly"], "exactly one state and no actions"),
        (["--method", "render", "--state", "a", "--state", "b"], "exactly one state"),
        (["--method", "render_interact", "--state", "a", "--state", "a=Go"], "must be unique"),
    ],
)
def test_bad_states_are_refused_with_exit_2(
    argv: list[str], message: str, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code, err = _refused(["capture", "http://127.0.0.1/x", *argv], capsys, tmp_path)
    assert code == 2
    assert message in err
    assert err.startswith("mihenk capture: error: ")
    assert len(err.strip().splitlines()) == 1


def test_a_malformed_proxy_variable_is_one_line_and_exit_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, "ftp://127.0.0.1:9")
    code, err = _refused(["capture", "http://127.0.0.1/x"], capsys, tmp_path)
    assert code == 2
    assert err.startswith("mihenk capture: error: cannot set up the http client: ")
    assert len(err.strip().splitlines()) == 1


def test_a_proxy_that_needs_a_missing_package_is_one_line_and_exit_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, "socks5://127.0.0.1:9")
    code, err = _refused(["capture", "http://127.0.0.1/x"], capsys, tmp_path)
    assert code == 2
    assert "cannot set up the http client" in err
    assert len(err.strip().splitlines()) == 1


# --- output -------------------------------------------------------------------------------------


def test_a_console_that_cannot_show_a_letter_gets_a_question_mark() -> None:
    raw = io.BytesIO()
    console = io.TextIOWrapper(
        raw, encoding="ascii", errors="strict", newline="\n", write_through=True
    )
    cli._emit(console, "Aylık 199 TL")
    assert raw.getvalue() == b"Ayl?k 199 TL\n"


def test_no_console_at_all_is_not_an_error() -> None:
    cli._emit(None, "anything")


def test_the_pace_between_requests_to_one_site_is_two_seconds() -> None:
    assert cli.PACE_INTERVAL_S == 2.0
