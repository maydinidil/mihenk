"""Fails when a runtime dependency's licence is not on the allow-list (design §18).

Python: the runtime closure from `uv export --no-dev`, read from installed metadata (an entry of
tools/license_overrides.toml for the installed version first, then License-Expression, then
classifiers). A package that is missing here is skipped only when its environment marker names
another platform; otherwise it is a problem.
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
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement

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
_OPERATORS = frozenset({"AND", "OR", "WITH"})
_TOKEN = re.compile(r"\s*(?:[()]|[A-Za-z0-9.+:-]+)")


@dataclass(frozen=True)
class Override:
    """A licence read by hand for one version of one package."""

    spdx: str
    version: str


def _tokenize(expression: str) -> list[str]:
    tokens: list[str] = []
    text = expression.rstrip()
    pos = 0
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if match is None:
            bad = text[pos:].lstrip()[0]
            raise ValueError(f"unexpected character {bad!r} in licence expression: {expression!r}")
        tokens.append(match.group().strip())
        pos = match.end()
    return tokens


def spdx_allowed(expression: str, allowed: frozenset[str]) -> bool:
    tokens = _tokenize(expression)
    pos = 0

    def is_operator(token: str) -> bool:
        return token.upper() in _OPERATORS

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
        if token == ")" or is_operator(token):  # noqa: S105  # an SPDX parser token
            raise ValueError(f"unexpected {token!r} in licence expression: {expression!r}")
        if pos < len(tokens) and tokens[pos].upper() == "WITH":
            pos += 1
            if pos >= len(tokens) or tokens[pos] in ("(", ")") or is_operator(tokens[pos]):
                raise ValueError(
                    f"WITH needs an exception id in licence expression: {expression!r}"
                )
            pos += 1  # an exception never makes a licence acceptable by itself
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


def parse_requirements(exported: str) -> list[Requirement]:
    """The requirements in `uv export` output, each with its environment marker."""
    found = []
    for line in exported.splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "-")):
            found.append(Requirement(line))
    return found


def python_runtime_requirements() -> list[Requirement]:
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv is needed for the licence check")
    exported = subprocess.run(
        [
            uv,
            "export",
            "--locked",
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
    return parse_requirements(exported)


def python_runtime_names() -> list[str]:
    return [requirement.name for requirement in python_runtime_requirements()]


def _classifier_expression(classifiers: list[str]) -> str | None:
    """The mapped licence, or None when any `License ::` classifier is not in the map."""
    licences = [c for c in classifiers if c.startswith("License ::")]
    if not licences or any(c not in _CLASSIFIERS for c in licences):
        return None
    return _CLASSIFIERS[licences[0]]


def python_expression(name: str, overrides: dict[str, Override]) -> str | None:
    meta = metadata.metadata(name)
    override = overrides.get(name.lower())
    if override is not None and override.version == meta["Version"]:
        return override.spdx
    if meta.get("License-Expression"):
        return str(meta["License-Expression"])
    return _classifier_expression(meta.get_all("Classifier") or [])


def load_overrides() -> dict[str, Override]:
    overrides_file = ROOT / "tools" / "license_overrides.toml"
    table = tomllib.loads(overrides_file.read_text("utf-8"))
    overrides: dict[str, Override] = {}
    for name, entry in table.items():
        for key in ("spdx", "version"):
            if key not in entry:
                raise ValueError(f"tools/license_overrides.toml: [{name}] has no {key!r}")
        overrides[name.lower()] = Override(spdx=entry["spdx"], version=entry["version"])
    return overrides


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


def _unknown_python_licence(name: str, overrides: dict[str, Override]) -> str:
    override = overrides.get(name.lower())
    if override is None:
        return f"python {name}: licence unknown; add it to tools/license_overrides.toml"
    return (
        f"python {name}: licence unknown; tools/license_overrides.toml lists version "
        f"{override.version} but {metadata.version(name)} is installed, so re-read the licence "
        "and update the entry"
    )


def _check_python(overrides: dict[str, Override], problems: list[str]) -> None:
    for requirement in python_runtime_requirements():
        name = requirement.name
        try:
            expression = python_expression(name, overrides)
        except metadata.PackageNotFoundError:
            if requirement.marker is not None and not requirement.marker.evaluate():
                print(
                    f"skip {name}: not installed on this platform (checked on the other CI system)"
                )
            else:
                problems.append(
                    f"python {name}: not installed, but this platform needs it; run `uv sync`"
                )
            continue
        if expression is None:
            problems.append(_unknown_python_licence(name, overrides))
        elif name.lower() in APPROVED_LGPL:
            continue
        else:
            try:
                allowed = spdx_allowed(expression, ALLOWED)
            except ValueError as exc:
                problems.append(f"python {name}: {exc}")
                continue
            if not allowed:
                problems.append(f"python {name}: {expression}")


def _check_npm(problems: list[str]) -> None:
    for name in npm_runtime_packages():
        package_json = ROOT / "web" / "node_modules" / name / "package.json"
        expression = json.loads(package_json.read_text("utf-8")).get("license")
        if not isinstance(expression, str):
            problems.append(f"npm {name}: {expression!r}")
            continue
        try:
            allowed = spdx_allowed(expression, ALLOWED)
        except ValueError as exc:  # npm allows free text such as "SEE LICENSE IN LICENSE.md"
            problems.append(f"npm {name}: {exc}")
            continue
        if not allowed:
            problems.append(f"npm {name}: {expression!r}")


def main() -> int:
    problems: list[str] = []
    _check_python(load_overrides(), problems)
    _check_npm(problems)
    for problem in problems:
        print("LICENCE PROBLEM", problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
