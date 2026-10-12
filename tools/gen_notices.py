"""Writes THIRD_PARTY_NOTICES.txt at the repository root (design §17, §18).

The file reproduces the licence and notice texts of everything that ships with mihenk, in this
order, each part under a heading with the package name, version and SPDX expression:

1. every runtime Python distribution (the closure from `uv export --no-dev`);
2. the Node.js binary and Playwright core bundled in the playwright wheel (`playwright/driver/`);
3. the Microsoft WebView2 SDK files bundled in the pywebview wheel (`webview/lib/`);
4. PyInstaller's licence section holding the bootloader exception;
5. the CPython runtime that PyInstaller embeds in the frozen app (PSF-2.0);
6. every production npm package of the screens.

Everything is read from what is already installed; nothing is fetched. The wheel build
(hatch_build.py) refuses to run without this file, and the file is git-ignored on purpose.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import sys
from collections.abc import Sequence
from importlib import metadata
from itertools import pairwise
from pathlib import Path

try:
    from tools import check_licenses
except ModuleNotFoundError:
    # Run as a script (python tools/gen_notices.py): only tools/ is on sys.path, not the root.
    import check_licenses

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "THIRD_PARTY_NOTICES.txt"
NO_LICENCE_FILE = "(no licence file found; nothing to reproduce here)"
_CODE_SUFFIXES = frozenset({".py", ".pyc", ".pyi", ".pyd", ".so", ".dll", ".js", ".mjs", ".ts"})
_BANNER = re.compile(r"^={3,}[ \t]*\n[ \t]*(?P<title>[^\n]+?)[ \t]*\n={3,}[ \t]*$", re.MULTILINE)
_RULE = "=" * 78


def _is_notice_name(name: str) -> bool:
    """LICENSE*, LICENCE*, COPYING*, NOTICE*, ThirdPartyNotices*, and bundled `x.js.LICENSE` files."""
    lowered = name.lower()
    if Path(lowered).suffix in _CODE_SUFFIXES:
        return False
    return lowered.startswith(("license", "licence", "copying", "notice", "thirdpartynotices")) or (
        lowered.endswith((".license", ".licence"))
    )


def _read(path: Path) -> str:
    """The file's text, which must be UTF-8: a licence is never silently reproduced with
    replacement characters."""
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path} is not UTF-8 text (byte {exc.start}: {exc.reason})") from exc
    return text.replace("\r\n", "\n").strip("\n").rstrip()


def _heading(title: str) -> str:
    return f"{_RULE}\n{title}\n{_RULE}"


def _file_block(label: str, text: str) -> str:
    return f"--- {label} ---\n{text}"


def _is_distribution_notice(path: metadata.PackagePath) -> bool:
    if _is_notice_name(path.name):
        return True
    # PEP 639 puts every licence file under <name>.dist-info/licenses/, whatever it is called.
    return (
        len(path.parts) > 2
        and path.parts[0].endswith(".dist-info")
        and path.parts[1] == "licenses"
        and path.suffix not in _CODE_SUFFIXES
    )


def distribution_notice(
    dist: metadata.Distribution, expression: str, skip_under: tuple[str, ...] = ()
) -> str:
    """Heading plus the full text of every licence and notice file the distribution ships.

    Files under a `skip_under` prefix are left out because a later part reproduces them.
    """
    parts = [_heading(f"{dist.metadata['Name']} {dist.version} ({expression})")]
    seen: set[str] = set()
    files = sorted(
        (
            f
            for f in dist.files or []
            if _is_distribution_notice(f) and not f.as_posix().startswith(skip_under)
        ),
        key=lambda f: f.as_posix(),
    )
    for file in files:
        path = Path(str(dist.locate_file(file)))
        if not path.is_file():
            continue
        text = _read(path)
        if text in seen:
            continue
        seen.add(text)
        parts.append(_file_block(file.as_posix(), text))
    if len(parts) == 1:
        declared = [
            f"{field}: {dist.metadata.get(field)}"
            for field in ("Author", "Home-page")
            if dist.metadata.get(field)
        ]
        parts.append("\n".join([NO_LICENCE_FILE, *declared]))
    return "\n\n".join(parts)


def folder_notice(title: str, folder: Path) -> str:
    """Heading plus every licence or notice file found anywhere under `folder`."""
    parts = [_heading(title)]
    if folder.is_dir():
        for path in sorted(p for p in folder.rglob("*") if p.is_file() and _is_notice_name(p.name)):
            parts.append(_file_block(path.relative_to(folder).as_posix(), _read(path)))
    if len(parts) == 1:
        parts.append(NO_LICENCE_FILE)
    return "\n\n".join(parts)


def bootloader_exception_section(copying: str) -> str:
    """The banner-delimited section of PyInstaller's COPYING.txt that holds the bootloader
    exception (not the full GPL, Apache and MIT texts that follow it)."""
    text = copying.replace("\r\n", "\n")
    starts = [m.start() for m in _BANNER.finditer(text)] + [len(text)]
    for begin, end in pairwise(starts):
        section = text[begin:end]
        if "Bootloader Exception" in section:
            return section.strip("\n").rstrip()
    raise ValueError("PyInstaller's COPYING.txt has no section with the bootloader exception")


def _pyinstaller_notice() -> str:
    dist = metadata.distribution("pyinstaller")
    files = [f for f in dist.files or [] if f.name.upper().startswith("COPYING")]
    if not files:
        raise ValueError("the installed PyInstaller ships no COPYING file")
    section = bootloader_exception_section(_read(Path(str(dist.locate_file(files[0])))))
    heading = _heading(f"PyInstaller {dist.version} (GPL-2.0-or-later WITH Bootloader-exception)")
    return f"{heading}\n\n{_file_block(files[0].as_posix() + ' (bootloader exception section)', section)}"


def python_runtime_notice(prefix: Path, version: str) -> str:
    """Heading plus the licence text of the CPython runtime installed under `prefix`.

    The frozen app embeds this runtime, so its licence ships with the app. `LICENSE.txt` is
    the usual file; other LICENSE or COPYING names are taken when it is missing. Unix builds
    keep the file in the standard library folder (`lib/python3.x/`), so that is looked at last.
    """
    heading = _heading(f"Python {version} (PSF-2.0)")
    folders = [prefix, *sorted((prefix / "lib").glob("python3*"))]
    for folder in folders:
        if not folder.is_dir():
            continue
        files = sorted(p for p in folder.iterdir() if p.is_file() and _is_notice_name(p.name))
        files.sort(key=lambda p: (p.name != "LICENSE.txt", p.name != "LICENSE"))
        if files:
            return "\n\n".join([heading, _file_block(files[0].name, _read(files[0]))])
    return "\n\n".join([heading, NO_LICENCE_FILE])


def _npm_notice(name: str) -> str:
    folder = ROOT / "web" / "node_modules" / name
    package = json.loads((folder / "package.json").read_text("utf-8"))
    parts = [
        _heading(f"{name} {package.get('version', '?')} ({package.get('license', 'unknown')})")
    ]
    for path in sorted(p for p in folder.iterdir() if p.is_file() and _is_notice_name(p.name)):
        parts.append(_file_block(path.name, _read(path)))
    if len(parts) == 1:
        parts.append(NO_LICENCE_FILE)
    return "\n\n".join(parts)


def build_notices() -> tuple[str, list[str]]:
    """The whole file's text, and a list of the parts that had no licence file to reproduce."""
    overrides = check_licenses.load_overrides()
    missing: list[str] = []
    sections: list[str] = [
        "THIRD-PARTY NOTICES for mihenk\n\n"
        "mihenk is licensed under PolyForm-Noncommercial-1.0.0 (see LICENSE and NOTICE). This file\n"
        "reproduces the licence and notice texts of the software that ships with it. It is\n"
        "generated by tools/gen_notices.py; do not edit it by hand."
    ]

    def add(label: str, text: str) -> None:
        if NO_LICENCE_FILE in text:
            missing.append(label)
        sections.append(text)

    names = sorted(set(check_licenses.python_runtime_names()), key=str.lower)
    for name in names:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            print(f"skip {name}: not installed on this platform", file=sys.stderr)
            continue
        expression = check_licenses.python_expression(name, overrides) or "unknown"
        # The playwright and pywebview folders that parts 2 and 3 reproduce are left out here.
        skip = {"playwright": ("playwright/driver/",), "pywebview": ("webview/lib/",)}
        add(f"python {name}", distribution_notice(dist, expression, skip.get(name.lower(), ())))

    playwright = metadata.distribution("playwright")
    add(
        "playwright/driver",
        folder_notice(
            f"playwright {playwright.version} driver: bundled Node.js and Playwright core (Apache-2.0)",
            Path(str(playwright.locate_file("playwright/driver"))),
        ),
    )
    pywebview = metadata.distribution("pywebview")
    add(
        "webview/lib",
        folder_notice(
            f"pywebview {pywebview.version} webview/lib: Microsoft WebView2 SDK files",
            Path(str(pywebview.locate_file("webview/lib"))),
        ),
    )
    sections.append(_pyinstaller_notice())
    add(
        "python runtime",
        python_runtime_notice(Path(sys.base_prefix), platform.python_version()),
    )
    for name in sorted(set(check_licenses.npm_runtime_packages()), key=str.lower):
        add(f"npm {name}", _npm_notice(name))
    return "\n\n\n".join(sections) + "\n", missing


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write THIRD_PARTY_NOTICES.txt.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when any part has no licence file (the default is to warn and exit 0)",
    )
    args = parser.parse_args(argv)
    try:
        text, missing = build_notices()
    except ValueError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT.name}: {len(text.splitlines())} lines")
    for label in missing:
        print(f"WARNING no licence file found for {label}", file=sys.stderr)
    return 1 if args.strict and missing else 0


if __name__ == "__main__":
    sys.exit(main())
