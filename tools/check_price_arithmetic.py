"""Fails on arithmetic involving price fields (design §4, "never reconcile").

Scans every Python file under src/ and tools/, and every TypeScript file under web/src/,
recursively. The only exempt file is src/mihenk/verify/checks.py, whose results are flags.
From stage 2 the field list comes from mihenk.core.fields; until then it is listed here.
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

PRICE_FIELDS = frozenset(
    {
        "monthly_price",
        "annual_price_per_month",
        "annual_total",
        "promo_price",
        "renewal_price",
        "setup_fee",
        "unit_amount",
        "flat_amount",
    }
)
EXEMPT = frozenset({Path("src/mihenk/verify/checks.py")})
_ARITH = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


_TS_NAMES = "|".join(sorted(PRICE_FIELDS | {_camel(f) for f in PRICE_FIELDS}))
_TS_PATTERN = re.compile(
    rf"\b({_TS_NAMES})\b\s*(\*\*|[-+*/%])(?!=)|(?<![=!<>])(\*\*|[-+*/%])=?\s*\b({_TS_NAMES})\b"
)


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    field: str


def _names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute):
        return {node.attr}
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        value = node.slice.value
        return {value} if isinstance(value, str) else set()
    return set()


def python_violations(path: Path, source: str) -> list[Violation]:
    found: list[Violation] = []
    for node in ast.walk(ast.parse(source, filename=str(path))):
        hits: set[str] = set()
        if isinstance(node, ast.BinOp) and isinstance(node.op, _ARITH):
            hits = (_names(node.left) | _names(node.right)) & PRICE_FIELDS
        elif isinstance(node, ast.AugAssign) and isinstance(node.op, _ARITH):
            hits = (_names(node.target) | _names(node.value)) & PRICE_FIELDS
        found.extend(Violation(path, node.lineno, name) for name in sorted(hits))
    return found


def typescript_violations(path: Path, source: str) -> list[Violation]:
    found: list[Violation] = []
    for number, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith(("//", "*", "import ")):
            continue
        for match in _TS_PATTERN.finditer(line):
            found.append(Violation(path, number, match.group(1) or match.group(4)))
    return found


def scan(root: Path) -> list[Violation]:
    found: list[Violation] = []
    for folder in (root / "src", root / "tools"):
        for file in sorted(folder.rglob("*.py")) if folder.is_dir() else []:
            if file.relative_to(root) in EXEMPT or file.name == "check_price_arithmetic.py":
                continue
            found.extend(python_violations(file, file.read_text("utf-8")))
    web = root / "web" / "src"
    for file in sorted(web.rglob("*.ts*")) if web.is_dir() else []:
        if file.name == "schema.ts":
            continue
        found.extend(typescript_violations(file, file.read_text("utf-8")))
    return found


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    violations = scan(root)
    for v in violations:
        print(f"{v.path}:{v.line}: arithmetic on price field '{v.field}' (never reconcile, §4)")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
