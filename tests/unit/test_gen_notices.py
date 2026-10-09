from importlib import metadata
from pathlib import Path

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
