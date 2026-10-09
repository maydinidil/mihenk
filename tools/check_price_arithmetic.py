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
# Calls whose result is text, and the calls that read a field by its name.
_TEXT_CALLS = frozenset({"str", "repr", "format", "ascii"})
_LOOKUPS = frozenset({"get", "pop", "setdefault", "getattr"})


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


_TS_NAMES = "|".join(sorted(PRICE_FIELDS | {_camel(f) for f in PRICE_FIELDS}))
# An arithmetic operator or its compound assignment (`*`, `**=`, `+=` ...). Never `=`, `=>`, `==`,
# `===`, `!==`, `>=` or `<=`: none of those starts with one of these characters.
_TS_OP = r"(?:\*\*=?|[-+*/%]=?)"
# `a.b?.c!.` or `rows[0].` in front of a field name.
_TS_MEMBERS = r"(?:[\w$]+(?:\[[^\[\]\n]*\])*[?!]*(?:\?\.|\.))*"
# A price field, then an operator. `!`, `)` and the `"]` / `']` that close a subscript may sit
# between them, and whitespace (newlines included) may surround the operator.
_TS_LEFT = rf"\b(?P<left>{_TS_NAMES})\b(?:\s*(?:[!)]|[\"']\]))*\s*{_TS_OP}"
# An operator, then a price field: a member chain, optional `(`, or a subscript like
# `row["monthlyPrice"]`.
_TS_RIGHT = (
    rf"{_TS_OP}[(\s]*{_TS_MEMBERS}"
    rf"(?:\b(?P<right>{_TS_NAMES})\b"
    rf"|[\w$]+(?:\[[^\[\]\n]*\])*?\[\s*[\"'](?P<sub>{_TS_NAMES})[\"']\s*\])"
)
_TS_PATTERN = re.compile(f"{_TS_LEFT}|{_TS_RIGHT}")


def _neighbour(source: str, index: int, step: int) -> str:
    """The first character after (step 1) or before (step -1) `index` that is not whitespace."""
    k = index + step
    while 0 <= k < len(source) and source[k].isspace():
        k += step
    return source[k] if 0 <= k < len(source) else ""


def _blank_typescript(source: str) -> str:
    """Replace comments and the contents of string and template literals with spaces.

    Newlines stay, so offsets and line numbers do not move. Code inside a template's `${...}`
    stays. The text of a string that is the whole content of a `[...]` subscript also stays, so
    `row["monthlyPrice"]` is still seen. A single- or double-quoted string ends at its closing
    quote or at the end of the line, so an apostrophe in JSX text blanks only the rest of its line.
    """
    out = list(source)
    size = len(source)

    def blank(begin: int, end: int) -> None:
        for k in range(begin, end):
            if out[k] != "\n":
                out[k] = " "

    def template_text(begin: int, braces: list[int]) -> int:
        """Blank template text from `begin`; return where code resumes (after the closing
        backtick, or after a `${` that opens an expression)."""
        k = begin
        while k < size:
            if source[k] == "`":
                return k + 1
            if source.startswith("${", k):
                braces.append(0)
                return k + 2
            step = 2 if source[k] == "\\" else 1
            blank(k, min(k + step, size))
            k += step
        return size

    braces: list[int] = []  # open `{` count inside each `${...}` that is still open
    i = 0
    while i < size:
        char = source[i]
        if source.startswith("//", i):
            end = source.find("\n", i)
            end = size if end == -1 else end
            blank(i, end)
            i = end
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            end = size if end == -1 else end + 2
            blank(i, end)
            i = end
        elif char in "'\"":
            end = i + 1
            while end < size and source[end] not in (char, "\n"):
                end += 2 if source[end] == "\\" else 1
            end = min(end, size)
            closed = end < size and source[end] == char
            if not (
                closed and _neighbour(source, i, -1) == "[" and _neighbour(source, end, 1) == "]"
            ):
                blank(i + 1, end)
            i = end + 1 if closed else end
        elif char == "`":
            i = template_text(i + 1, braces)
        elif braces and char == "{":
            braces[-1] += 1
            i += 1
        elif braces and char == "}":
            if braces[-1] == 0:
                braces.pop()
                i = template_text(i + 1, braces)
            else:
                braces[-1] -= 1
                i += 1
        else:
            i += 1
    return "".join(out)


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    field: str


def _str_value(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_text(node: ast.AST) -> bool:
    """Whether the expression is text: a string, an f-string, a `str()`-style call, or `+` / `%`
    that builds one."""
    if isinstance(node, ast.JoinedStr) or _str_value(node) is not None:
        return True
    if isinstance(node, ast.BinOp):
        return _builds_text(node)
    if isinstance(node, ast.Call):
        func = node.func
        return (isinstance(func, ast.Name) and func.id in _TEXT_CALLS) or (
            isinstance(func, ast.Attribute) and func.attr == "format"
        )
    return False


def _builds_text(node: ast.BinOp) -> bool:
    """`"a" + x` is concatenation and `"%s" % x` is formatting, not arithmetic."""
    if isinstance(node.op, ast.Add):
        return _is_text(node.left) or _is_text(node.right)
    if isinstance(node.op, ast.Mod):
        return _is_text(node.left)
    return False


def _names(node: ast.AST) -> set[str]:
    """Every name that appears anywhere in the operand: variables, attributes, `x["name"]`,
    `x.get("name")` and `getattr(x, "name")`."""
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            found.add(child.id)
        elif isinstance(child, ast.Attribute):
            found.add(child.attr)
        elif isinstance(child, ast.Subscript):
            if (key := _str_value(child.slice)) is not None:
                found.add(key)
        elif isinstance(child, ast.Call) and _is_lookup(child):
            keys = (_str_value(arg) for arg in child.args[:2])
            found.update(key for key in keys if key is not None)
    return found


def _is_lookup(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr in _LOOKUPS
    return isinstance(func, ast.Name) and func.id in _LOOKUPS


def python_violations(path: Path, source: str) -> list[Violation]:
    found: list[Violation] = []
    for node in ast.walk(ast.parse(source, filename=str(path))):
        hits: set[str] = set()
        if isinstance(node, ast.BinOp) and isinstance(node.op, _ARITH) and not _builds_text(node):
            hits = (_names(node.left) | _names(node.right)) & PRICE_FIELDS
        elif (
            isinstance(node, ast.AugAssign)
            and isinstance(node.op, _ARITH)
            and not (isinstance(node.op, ast.Add) and _is_text(node.value))
        ):
            hits = (_names(node.target) | _names(node.value)) & PRICE_FIELDS
        for name in sorted(hits):
            violation = Violation(path, node.lineno, name)
            if violation not in found:
                found.append(violation)
    return sorted(found, key=lambda v: (v.line, v.field))


def typescript_violations(path: Path, source: str) -> list[Violation]:
    text = _blank_typescript(source)
    found: list[Violation] = []
    for match in _TS_PATTERN.finditer(text):
        # The line is where the expression starts: the field for `price *`, the operator for
        # `* price`, so `base *` / `row.monthlyPrice` on two lines reports the first.
        line = text.count("\n", 0, match.start()) + 1
        field = match.group("left") or match.group("right") or match.group("sub")
        violation = Violation(path, line, field)
        if violation not in found:
            found.append(violation)
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
