"""`mihenk capture` end to end against pages on 127.0.0.1.

Runs that need a browser go through a child process (`python -m mihenk capture ...`), never
`cli.main` in the test process: the command starts its own Playwright session, and the sync API
allows one per thread (Task 0.6).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from itertools import pairwise
from pathlib import Path

import pytest

from mihenk import cli
from tests.helpers.pages import serve_page
from tests.helpers.site import LocalSite


@pytest.fixture
def no_pacing(monkeypatch: pytest.MonkeyPatch) -> None:
    # The two seconds between requests to one site are pinned in tests/unit/test_cli_options.py.
    # Runs in this process do not wait for them; runs in a child process keep the real pace.
    monkeypatch.setattr(cli, "PACE_INTERVAL_S", 0.0)


def _lines(text: str) -> list[list[str]]:
    return [line.split("\t") for line in text.splitlines()]


def _snapshot_folders(data_dir: Path) -> list[Path]:
    """Every state folder: snapshots/<run>/<key>/<state>."""
    return sorted(path for path in (data_dir / "snapshots").glob("*/*/*") if path.is_dir())


@pytest.mark.usefixtures("no_pacing")
def test_capture_by_fetch_writes_a_snapshot_and_prints_one_line(
    site: LocalSite, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    url = serve_page(site, "static-table")
    code = cli.main(["capture", url, "--data-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    (folder,) = _snapshot_folders(tmp_path)
    assert folder.name == "default"
    assert folder.parent.name == "127-0-0-1-static-table"  # the default key
    assert (folder / "text.txt").is_file()
    ((label, status, detail, printed_folder),) = _lines(out)
    assert (label, status, detail) == ("default", "ok", "captured")
    assert Path(printed_folder) == folder
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    assert meta["method"] == "fetch"
    assert re.fullmatch("[A-Z]{2}", meta["collection_country"])


@pytest.mark.usefixtures("no_pacing")
def test_key_and_country_options_name_the_folder_and_the_provenance(
    site: LocalSite, tmp_path: Path
) -> None:
    url = serve_page(site, "static-table")
    code = cli.main(
        ["capture", url, "--key", "contoso-crm", "--country", "nl", "--data-dir", str(tmp_path)]
    )
    assert code == 0
    (folder,) = _snapshot_folders(tmp_path)
    assert folder.parent.name == "contoso-crm"
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    assert meta["collection_country"] == "NL"


@pytest.mark.usefixtures("no_pacing")
def test_the_exit_code_is_1_and_the_line_says_why_for_a_bot_wall(
    site: LocalSite, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    url = serve_page(site, "bot-wall")
    code = cli.main(["capture", url, "--data-dir", str(tmp_path)])
    ((_, status, detail, folder),) = _lines(capsys.readouterr().out)
    assert code == 1
    assert status == "needs_human"
    assert "bot check" in detail
    assert Path(folder).is_dir()  # kept as evidence


@pytest.mark.usefixtures("no_pacing")
def test_robots_blocks_the_page_unless_ignored(
    site: LocalSite, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    site.add("/robots.txt", "User-agent: *\nDisallow: /\n", content_type="text/plain")
    url = serve_page(site, "static-table")
    assert cli.main(["capture", url, "--data-dir", str(tmp_path)]) == 1
    ((_, status, detail, folder),) = _lines(capsys.readouterr().out)
    assert status == "blocked_by_robots"
    assert "disallowed" in detail
    assert folder == "-"
    assert "/static-table" not in site.hits
    assert _snapshot_folders(tmp_path) == []

    assert cli.main(["capture", url, "--ignore-robots", "--data-dir", str(tmp_path)]) == 0
    ((_, status, _, _),) = _lines(capsys.readouterr().out)
    assert status == "ok"
    assert len(_snapshot_folders(tmp_path)) == 1


@pytest.mark.usefixtures("no_pacing")
def test_an_address_that_is_not_a_web_page_is_refused_with_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(["capture", "ftp://127.0.0.1/pricing", "--data-dir", str(tmp_path)])
    ((_, status, detail, _),) = _lines(capsys.readouterr().out)
    assert code == 1
    assert status == "http_error"
    assert detail.startswith("not a valid http(s) URL")


@pytest.mark.usefixtures("no_pacing")
def test_a_snapshot_path_that_is_too_long_is_one_clear_line_and_exit_1(
    site: LocalSite, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_dir = tmp_path / ("d" * 200)  # the snapshot path would pass 259 characters
    url = serve_page(site, "static-table")
    code = cli.main(["capture", url, "--data-dir", str(data_dir)])
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert len(captured.err.strip().splitlines()) == 1
    assert captured.err.startswith("mihenk capture: failed: ValueError: snapshot path too long")
    assert not data_dir.exists()


@pytest.mark.usefixtures("no_pacing")
def test_a_data_folder_that_is_a_file_is_one_clear_line_and_exit_1(
    site: LocalSite, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_dir = tmp_path / "a-file"
    data_dir.write_text("not a folder", encoding="utf-8")
    url = serve_page(site, "static-table")
    code = cli.main(["capture", url, "--data-dir", str(data_dir)])
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert len(captured.err.strip().splitlines()) == 1
    assert re.match(r"mihenk capture: failed: \w*Error: ", captured.err)


def test_every_request_to_one_site_is_paced_including_robots_txt_redirect_hops(
    site: LocalSite, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # http://x/robots.txt -> https://x/robots.txt is the common case; here a redirect on one site.
    monkeypatch.setattr(cli, "PACE_INTERVAL_S", 0.5)
    site.redirect("/robots.txt", "/real-robots.txt")
    site.add("/real-robots.txt", "User-agent: *\nAllow: /\n", content_type="text/plain")
    url = serve_page(site, "static-table")
    assert cli.main(["capture", url, "--data-dir", str(tmp_path)]) == 0
    assert site.hits == ["/robots.txt", "/real-robots.txt", "/static-table"]
    gaps = [later - earlier for earlier, later in pairwise(site.hit_times)]
    assert all(gap >= 0.45 for gap in gaps), gaps


def test_a_robots_txt_redirect_loop_is_paced_on_every_hop(
    site: LocalSite, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "PACE_INTERVAL_S", 0.2)
    site.redirect("/robots.txt", "/robots-a")
    site.redirect("/robots-a", "/robots-b")
    site.redirect("/robots-b", "/robots-a")
    url = serve_page(site, "static-table")
    assert cli.main(["capture", url, "--data-dir", str(tmp_path)]) == 1  # unreachable: disallowed
    assert "/static-table" not in site.hits
    assert len(site.hits) == 6  # robots.txt and five redirects
    gaps = [later - earlier for earlier, later in pairwise(site.hit_times)]
    assert all(gap >= 0.18 for gap in gaps), gaps


def _run_module(*args: str) -> subprocess.CompletedProcess[str]:
    """`python -m mihenk ...` in a child process, as a person starts it."""
    return subprocess.run(
        [sys.executable, "-m", "mihenk", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=False,
    )


def test_python_dash_m_mihenk_capture_reaches_the_cli() -> None:
    result = _run_module("capture", "--help")
    assert result.returncode == 0, result.stderr
    assert "usage: mihenk capture" in result.stdout
    assert "--ignore-robots" in result.stdout


def test_python_dash_m_mihenk_capture_by_fetch_uses_the_real_pace(
    site: LocalSite, tmp_path: Path
) -> None:
    url = serve_page(site, "static-table")
    result = _run_module("capture", url, "--data-dir", str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    ((label, status, _, folder),) = _lines(result.stdout)
    assert (label, status) == ("default", "ok")
    assert Path(folder).is_dir()
    assert site.hits[:2] == ["/robots.txt", "/static-table"]
    # Two seconds between requests to one site (design §8.2), the robots.txt request included.
    assert site.hit_times[1] - site.hit_times[0] >= 1.9


def test_every_state_gets_its_own_line_in_a_child_process(tmp_path: Path) -> None:
    # The address is refused before any page is requested, so no browser is needed, but the
    # command still starts its Playwright session for a render method.
    result = _run_module(
        "capture",
        "gopher://127.0.0.1/",
        "--method",
        "render_interact",
        "--state",
        "annual",
        "--state",
        "monthly=Monthly",
        "--data-dir",
        str(tmp_path),
    )
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert "Traceback" not in result.stderr
    assert [line[:2] for line in _lines(result.stdout)] == [
        ["annual", "http_error"],
        ["monthly", "http_error"],
    ]


@pytest.mark.browser
@pytest.mark.usefixtures("browser")  # skips, or fails under MIHENK_REQUIRE_BROWSER=1, without one
def test_render_interact_in_a_child_process_captures_both_states(
    site: LocalSite, tmp_path: Path
) -> None:
    url = serve_page(site, "billing-toggle")
    result = _run_module(
        "capture",
        url,
        "--method",
        "render_interact",
        "--state",
        "annual",
        "--state",
        "monthly=Monthly",
        "--data-dir",
        str(tmp_path),
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "Traceback" not in result.stderr
    lines = _lines(result.stdout)
    assert [line[:3] for line in lines] == [
        ["annual", "ok", "captured"],
        ["monthly", "ok", "captured"],
    ]
    folders = {line[0]: Path(line[3]) for line in lines}
    assert sorted(path.name for path in _snapshot_folders(tmp_path)) == ["annual", "monthly"]
    for folder in folders.values():
        assert (folder / "screenshot.png").is_file()
    assert "billed yearly" in (folders["annual"] / "text.txt").read_text(encoding="utf-8")
    assert "billed monthly" in (folders["monthly"] / "text.txt").read_text(encoding="utf-8")
