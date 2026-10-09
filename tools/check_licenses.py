"""Fails when a runtime dependency's licence is not on the allow-list (design §18).

Python: the runtime closure from `uv export --no-dev`, read from installed metadata
(License-Expression first, then classifiers, then tools/license_overrides.toml).
Screens: production npm packages from `npm ls --omit=dev --all --json`.
GPL and AGPL always fail; LGPL fails unless listed in APPROVED_LGPL.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tomllib
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED = frozenset(
    {
        "MIT",
        "MIT-0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "Apache-2.0",
        "ISC",
        "0BSD",
        "PSF-2.0",
        "Python-2.0",
        "MPL-2.0",
        "Unlicense",
        "CC0-1.0",
        "BlueOak-1.0.0",
        "Zlib",
    }
)
APPROVED_LGPL: frozenset[str] = frozenset()  # package names Aydin approved, with a decision record
_CLASSIFIERS = {
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: BSD License": "BSD-3-Clause",
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: ISC License (ISCL)": "ISC",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
}


def spdx_allowed(expression: str, allowed: frozenset[str]) -> bool:
    tokens = re.findall(r"\(|\)|[A-Za-z0-9.+:-]+", expression)
    pos = 0

    def atom() -> bool:
        nonlocal pos
        if pos >= len(tokens):
            raise ValueError(f"incomplete licence expression: {expression!r}")
        token = tokens[pos]
        pos += 1
        if token == "(":  # noqa: S105  # an SPDX parser token, not a password
            value = either()
            if pos >= len(tokens) or tokens[pos] != ")":
                raise ValueError(f"unbalanced licence expression: {expression!r}")
            pos += 1
            return value
        if pos < len(tokens) and tokens[pos].upper() == "WITH":
            pos += 2  # an exception never makes a licence acceptable by itself
        return token in allowed

    def both() -> bool:
        nonlocal pos
        value = atom()
        while pos < len(tokens) and tokens[pos].upper() == "AND":
            pos += 1
            right = atom()
            value = value and right
        return value

    def either() -> bool:
        nonlocal pos
        value = both()
        while pos < len(tokens) and tokens[pos].upper() == "OR":
            pos += 1
            right = both()
            value = value or right
        return value

    result = either()
    if pos != len(tokens):
        raise ValueError(f"unexpected text in licence expression: {expression!r}")
    return result


def _python_runtime_names() -> list[str]:
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv is needed for the licence check")
    exported = subprocess.run(
        [
            uv,
            "export",
            "--color",
            "never",
            "--no-dev",
            "--no-emit-project",
            "--no-hashes",
            "--format",
            "requirements-txt",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    names = []
    for line in exported.splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "-")):
            names.append(re.split(r"[=<>!~;\s\[]", line, maxsplit=1)[0])
    return names


def _python_expression(name: str, overrides: dict[str, str]) -> str | None:
    if name.lower() in overrides:
        return overrides[name.lower()]
    meta = metadata.metadata(name)
    if meta.get("License-Expression"):
        return str(meta["License-Expression"])
    for classifier in meta.get_all("Classifier") or []:
        if classifier in _CLASSIFIERS:
            return _CLASSIFIERS[classifier]
    return None


def load_overrides() -> dict[str, str]:
    overrides_file = ROOT / "tools" / "license_overrides.toml"
    table = tomllib.loads(overrides_file.read_text("utf-8"))
    return {k.lower(): v["spdx"] for k, v in table.items()}


def npm_runtime_packages() -> list[str]:
    """Names of the production npm packages (the same set the licence check and the notices cover)."""
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("npm is needed for the licence check")
    tree = json.loads(
        subprocess.run(
            [npm, "ls", "--omit=dev", "--all", "--json"],
            cwd=ROOT / "web",
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    names: list[str] = []
    stack = list((tree.get("dependencies") or {}).items())
    while stack:
        name, node = stack.pop()
        names.append(name)
        stack.extend((node.get("dependencies") or {}).items())
    return names


def main() -> int:
    overrides = load_overrides()
    problems: list[str] = []
    for name in _python_runtime_names():
        try:
            expression = _python_expression(name, overrides)
        except metadata.PackageNotFoundError:
            print(f"skip {name}: not installed on this platform (checked on the other CI system)")
            continue
        if expression is None:
            problems.append(
                f"python {name}: licence unknown; add it to tools/license_overrides.toml"
            )
        elif name.lower() in APPROVED_LGPL:
            continue
        elif not spdx_allowed(expression, ALLOWED):
            problems.append(f"python {name}: {expression}")
    for name in npm_runtime_packages():
        package_json = ROOT / "web" / "node_modules" / name / "package.json"
        expression = json.loads(package_json.read_text("utf-8")).get("license")
        if not isinstance(expression, str) or not spdx_allowed(expression, ALLOWED):
            problems.append(f"npm {name}: {expression!r}")
    for problem in problems:
        print("LICENCE PROBLEM", problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
