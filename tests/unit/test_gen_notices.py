import json
import shutil
from importlib import metadata
from pathlib import Path

import pytest

from tools import check_licenses, gen_notices
from tools.gen_notices import (
    bootloader_exception_section,
    distribution_notice,
    folder_notice,
    python_runtime_notice,
)

MIT_TEXT = (
    "MIT License\n\nCopyright (c) 2026 Fake Author\n\nPermission is hereby granted, free of charge."
)


def _fake_distribution(root: Path) -> metadata.Distribution:
    info = root / "fakepkg-1.2.3.dist-info"
    (info / "licenses").mkdir(parents=True)
    (info / "METADATA").write_text(
        "Metadata-Version: 2.4\nName: fakepkg\nVersion: 1.2.3\nLicense-Expression: MIT\n",
        encoding="utf-8",
    )
    (info / "licenses" / "LICENSE").write_text(MIT_TEXT, encoding="utf-8")
    (info / "licenses" / "NOTICE").write_text("Fake NOTICE text for fakepkg.", encoding="utf-8")
    package = root / "fakepkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "license_helpers.py").write_text("SECRET_CODE = 1\n", encoding="utf-8")
    (package / "data.txt").write_text("not a licence", encoding="utf-8")
    records = [
        "fakepkg-1.2.3.dist-info/METADATA,,",
        "fakepkg-1.2.3.dist-info/licenses/LICENSE,,",
        "fakepkg-1.2.3.dist-info/licenses/NOTICE,,",
        "fakepkg/__init__.py,,",
        "fakepkg/license_helpers.py,,",
        "fakepkg/data.txt,,",
        "fakepkg-1.2.3.dist-info/RECORD,,",
    ]
    (info / "RECORD").write_text("\n".join(records) + "\n", encoding="utf-8")
    return metadata.PathDistribution(info)


def test_distribution_notice_has_heading_and_full_licence_text(tmp_path: Path) -> None:
    text = distribution_notice(_fake_distribution(tmp_path), "MIT")
    assert "fakepkg 1.2.3 (MIT)" in text
    assert MIT_TEXT in text
    assert "Fake NOTICE text for fakepkg." in text


def test_distribution_notice_skips_code_and_other_files(tmp_path: Path) -> None:
    text = distribution_notice(_fake_distribution(tmp_path), "MIT")
    assert "SECRET_CODE" not in text
    assert "not a licence" not in text


def test_distribution_notice_leaves_out_folders_a_later_part_reproduces(tmp_path: Path) -> None:
    dist = _fake_distribution(tmp_path)
    text = distribution_notice(dist, "MIT", skip_under=("fakepkg-1.2.3.dist-info/licenses/NOTICE",))
    assert MIT_TEXT in text
    assert "Fake NOTICE text for fakepkg." not in text


def test_distribution_without_a_licence_file_says_so(tmp_path: Path) -> None:
    info = tmp_path / "bare-0.1.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        "Metadata-Version: 2.4\nName: bare\nVersion: 0.1\n", encoding="utf-8"
    )
    (info / "RECORD").write_text("bare-0.1.dist-info/METADATA,,\n", encoding="utf-8")
    text = distribution_notice(metadata.PathDistribution(info), "MIT")
    assert "bare 0.1 (MIT)" in text
    assert "no licence file" in text


def test_folder_notice_collects_licence_files_recursively(tmp_path: Path) -> None:
    (tmp_path / "package" / "lib").mkdir(parents=True)
    (tmp_path / "LICENSE").write_text("Node licence text", encoding="utf-8")
    (tmp_path / "package" / "NOTICE").write_text("Playwright notice text", encoding="utf-8")
    (tmp_path / "package" / "ThirdPartyNotices.txt").write_text(
        "Third party list", encoding="utf-8"
    )
    (tmp_path / "package" / "lib" / "bundle.js.LICENSE").write_text(
        "Bundle licence", encoding="utf-8"
    )
    (tmp_path / "package" / "lib" / "bundle.js").write_text("var secretCode = 1;", encoding="utf-8")
    text = folder_notice("Playwright driver", tmp_path)
    assert "Playwright driver" in text
    for expected in (
        "Node licence text",
        "Playwright notice text",
        "Third party list",
        "Bundle licence",
    ):
        assert expected in text
    assert "secretCode" not in text


def test_folder_notice_for_an_empty_folder_says_so(tmp_path: Path) -> None:
    text = folder_notice("WebView2 SDK", tmp_path)
    assert "WebView2 SDK" in text
    assert "no licence file" in text


PYINSTALLER_COPYING = """\
================================
 The PyInstaller licensing terms
================================

Copyright (c) 2010-2023, PyInstaller Development Team

Bootloader Exception
--------------------

In addition to the permissions in the GNU General Public License, the
authors give you unlimited permission to link or embed compiled bootloader.

================================
GNU General Public License
================================

The full GPL text that must not be repeated.

================================
Apache License 2.0
================================

Apache text.
"""


def test_bootloader_exception_section_is_only_the_section_that_holds_it() -> None:
    section = bootloader_exception_section(PYINSTALLER_COPYING)
    assert "Bootloader Exception" in section
    assert "unlimited permission to link or embed" in section
    assert "must not be repeated" not in section
    assert "Apache text." not in section


PSF_TEXT = "A. HISTORY OF THE SOFTWARE\n\nPython was created in the early 1990s."


def test_python_runtime_notice_reproduces_the_runtime_licence(tmp_path: Path) -> None:
    (tmp_path / "LICENSE.txt").write_text(PSF_TEXT, encoding="utf-8")
    (tmp_path / "python.exe").write_text("not a licence", encoding="utf-8")
    text = python_runtime_notice(tmp_path, "3.13.13")
    assert "Python 3.13.13 (PSF-2.0)" in text
    assert PSF_TEXT in text
    assert "not a licence" not in text


def test_python_runtime_notice_accepts_a_licence_file_with_another_name(tmp_path: Path) -> None:
    (tmp_path / "LICENSE").write_text(PSF_TEXT, encoding="utf-8")
    text = python_runtime_notice(tmp_path, "3.13.13")
    assert PSF_TEXT in text
    assert "no licence file" not in text


def test_python_runtime_notice_without_a_licence_file_says_so(tmp_path: Path) -> None:
    text = python_runtime_notice(tmp_path, "3.13.13")
    assert "Python 3.13.13 (PSF-2.0)" in text
    assert "no licence file" in text


def test_python_runtime_notice_finds_the_licence_in_the_unix_standard_library_folder(
    tmp_path: Path,
) -> None:
    stdlib = tmp_path / "lib" / "python3.13"
    stdlib.mkdir(parents=True)
    (stdlib / "LICENSE.txt").write_text(PSF_TEXT, encoding="utf-8")
    assert PSF_TEXT in python_runtime_notice(tmp_path, "3.13.13")


# --- reading licence files -------------------------------------------------------------------


def test_a_licence_file_that_is_not_utf8_is_an_error_that_names_the_file(tmp_path: Path) -> None:
    (tmp_path / "LICENSE").write_bytes("Copyright © 2026".encode("latin-1"))
    with pytest.raises(ValueError, match="LICENSE") as error:
        folder_notice("Latin-1 licence", tmp_path)
    assert str(tmp_path) in str(error.value)
    assert "not UTF-8" in str(error.value)


def test_a_utf8_licence_file_with_windows_line_endings_still_reads(tmp_path: Path) -> None:
    (tmp_path / "LICENSE").write_bytes("Line one\r\nLine two, with a © sign\r\n".encode())
    text = folder_notice("Windows licence", tmp_path)
    assert "Line one\nLine two, with a © sign" in text


# --- the whole file, built from fake inputs ---------------------------------------------------


def _dist(root: Path, name: str, version: str, files: dict[str, str] | None = None) -> None:
    """A fake installed distribution; `files` maps a path under `root` to its text."""
    info = root / f"{name}-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\nLicense-Expression: MIT\n",
        encoding="utf-8",
    )
    records = [f"{info.name}/METADATA,,"]
    for relative, text in (files or {}).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        records.append(f"{relative},,")
    (info / "RECORD").write_text("\n".join(records) + "\n", encoding="utf-8")


class Env:
    def __init__(self, site: Path, root: Path) -> None:
        self.site = site
        self.root = root


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    """Every input of build_notices faked, with a licence file for every part (no gaps)."""
    site = tmp_path / "site"
    site.mkdir()
    monkeypatch.syspath_prepend(str(site))
    _dist(site, "fakepkg", "1.2.3", {"fakepkg-1.2.3.dist-info/licenses/LICENSE": MIT_TEXT})
    _dist(site, "playwright", "9.9", {"playwright/driver/LICENSE": "Node licence text"})
    _dist(site, "pywebview", "9.8", {"webview/lib/LICENSE": "WebView2 SDK licence text"})
    _dist(
        site, "pyinstaller", "9.7", {"pyinstaller-9.7.dist-info/COPYING.txt": PYINSTALLER_COPYING}
    )
    root = tmp_path / "repo"
    npm = root / "web" / "node_modules" / "fakenpm"
    npm.mkdir(parents=True)
    (npm / "package.json").write_text(
        json.dumps({"name": "fakenpm", "version": "4.5.6", "license": "ISC"}), encoding="utf-8"
    )
    (npm / "LICENSE").write_text("Fake npm licence text", encoding="utf-8")
    monkeypatch.setattr(gen_notices, "ROOT", root)
    monkeypatch.setattr(gen_notices, "OUTPUT", root / "THIRD_PARTY_NOTICES.txt")
    monkeypatch.setattr(check_licenses, "load_overrides", dict)
    monkeypatch.setattr(check_licenses, "python_runtime_names", lambda: ["fakepkg"])
    monkeypatch.setattr(check_licenses, "npm_runtime_packages", lambda: ["fakenpm"])
    monkeypatch.setattr(
        gen_notices,
        "python_runtime_notice",
        lambda prefix, version: f"Python {version} (PSF-2.0)\n{PSF_TEXT}",
    )
    return Env(site, root)


def test_build_notices_reproduces_every_part_in_order(env: Env) -> None:
    text, missing = gen_notices.build_notices()
    assert missing == []
    in_order = [
        "THIRD-PARTY NOTICES for mihenk",
        "fakepkg 1.2.3 (MIT)",
        MIT_TEXT,
        "playwright 9.9 driver",
        "Node licence text",
        "pywebview 9.8 webview/lib",
        "WebView2 SDK licence text",
        "PyInstaller 9.7 (GPL-2.0-or-later WITH Bootloader-exception)",
        "unlimited permission to link or embed",
        "Python 3.",
        PSF_TEXT,
        "fakenpm 4.5.6 (ISC)",
        "Fake npm licence text",
    ]
    positions = [text.index(piece) for piece in in_order]
    assert positions == sorted(positions)
    assert "must not be repeated" not in text  # only PyInstaller's bootloader section


def test_build_notices_lists_the_parts_without_a_licence_file(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutil.rmtree(env.site / "webview")
    _dist(env.site, "barepkg", "0.1")
    monkeypatch.setattr(check_licenses, "python_runtime_names", lambda: ["fakepkg", "barepkg"])
    text, missing = gen_notices.build_notices()
    assert missing == ["python barepkg", "webview/lib"]
    assert text.count(gen_notices.NO_LICENCE_FILE) == 2


def test_build_notices_skips_a_package_missing_on_this_platform(
    env: Env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_licenses, "python_runtime_names", lambda: ["fakepkg", "zzghost"])
    text, missing = gen_notices.build_notices()
    assert "zzghost" not in text
    assert missing == []
    assert "skip zzghost: not installed on this platform" in capsys.readouterr().err


def test_main_writes_the_file_and_exits_zero_even_with_a_gap(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.rmtree(env.site / "webview")
    assert gen_notices.main([]) == 0
    written = (env.root / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8")
    assert "fakepkg 1.2.3 (MIT)" in written
    captured = capsys.readouterr()
    assert "wrote THIRD_PARTY_NOTICES.txt" in captured.out
    assert "WARNING no licence file found for webview/lib" in captured.err


def test_main_strict_exits_one_on_a_gap_but_still_writes_the_file(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.rmtree(env.site / "webview")
    assert gen_notices.main(["--strict"]) == 1
    assert (env.root / "THIRD_PARTY_NOTICES.txt").is_file()
    assert "WARNING no licence file found for webview/lib" in capsys.readouterr().err


def test_main_strict_exits_zero_when_every_part_has_a_licence(env: Env) -> None:
    assert gen_notices.main(["--strict"]) == 0


def test_main_reports_a_licence_file_that_is_not_utf8_and_writes_nothing(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    (env.site / "playwright" / "driver" / "LICENSE").write_bytes("© Node".encode("latin-1"))
    assert gen_notices.main([]) == 1
    err = capsys.readouterr().err
    assert "ERROR" in err
    assert str(Path("playwright") / "driver" / "LICENSE") in err
    assert not (env.root / "THIRD_PARTY_NOTICES.txt").exists()
