from pathlib import Path

import pytest

from tools.check_price_arithmetic import python_violations, scan, typescript_violations


def test_flags_python_arithmetic_on_a_price_field() -> None:
    found = python_violations(Path("x.py"), "total = plan.monthly_price * 12\n")
    assert [(v.line, v.field) for v in found] == [(1, "monthly_price")]


def test_flags_augmented_assignment() -> None:
    assert python_violations(Path("x.py"), "annual_total += fee\n")


def test_ignores_unrelated_arithmetic() -> None:
    assert python_violations(Path("x.py"), "count = a + b\n") == []


def test_flags_typescript_arithmetic() -> None:
    assert typescript_violations(Path("x.ts"), "const y = row.monthlyPrice * 12;\n")


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("const t = 12 * row.monthlyPrice;\n", id="right operand is a property access"),
        pytest.param("const t = base + row.renewalPrice;\n", id="right operand after a plus"),
        pytest.param("total += row.monthlyPrice;\n", id="compound assignment, price on the right"),
        pytest.param("monthlyPrice *= 1.2;\n", id="compound assignment, bare name on the left"),
        pytest.param("row.monthlyPrice += 5;\n", id="compound assignment, property on the left"),
        pytest.param("setupFee /= 2;\n", id="compound division"),
        pytest.param('const t = row["monthlyPrice"] * 12;\n', id="subscript, double quotes"),
        pytest.param("const t = row['monthly_price'] * 12;\n", id="subscript, single quotes"),
        pytest.param('const t = 12 * row["monthlyPrice"];\n', id="subscript on the right"),
        pytest.param(
            "const t = row.monthlyPrice! * 12;\n", id="non-null assertion before operator"
        ),
        pytest.param("const t = (row.monthlyPrice) * 12;\n", id="parenthesised operand"),
        pytest.param("const t = Number(row.monthlyPrice) * 12;\n", id="wrapped in a call"),
        pytest.param("const t = `${row.monthlyPrice * 12} a month`;\n", id="template expression"),
        pytest.param(
            "const t = base\n  * row.monthlyPrice;\n", id="continuation starting with operator"
        ),
        pytest.param(
            "const t = base *\n  row.monthlyPrice;\n", id="operator at the end of the line"
        ),
    ],
)
def test_flags_typescript_arithmetic_forms(source: str) -> None:
    assert typescript_violations(Path("x.ts"), source)


def test_typescript_violation_line_is_where_the_expression_starts() -> None:
    source = "const a = 1;\nconst total = base *\n  row.monthlyPrice;\n"
    found = typescript_violations(Path("x.ts"), source)
    assert [(v.line, v.field) for v in found] == [(2, "monthlyPrice")]


def test_typescript_line_numbers_survive_blanked_comments() -> None:
    source = "/* a block\n   comment */\n// note\nconst t = 12 * row.monthlyPrice;\n"
    found = typescript_violations(Path("x.ts"), source)
    assert [(v.line, v.field) for v in found] == [(4, "monthlyPrice")]


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("// monthlyPrice * 12\n", id="line comment"),
        pytest.param("/* monthlyPrice * 12 */\n", id="block comment"),
        pytest.param("/**\n * Not monthlyPrice * 12.\n * renewalPrice - 1\n */\n", id="jsdoc"),
        pytest.param('const s = "monthlyPrice * 12";\n', id="double-quoted string"),
        pytest.param("const s = 'renewal_price - 1';\n", id="single-quoted string"),
        pytest.param("const s = `monthlyPrice * 12`;\n", id="template literal text"),
        pytest.param("if (x.monthlyPrice === null) return;\n", id="strict equality"),
        pytest.param("if (x.monthlyPrice !== undefined) return;\n", id="strict inequality"),
        pytest.param("if (monthlyPrice >= 0) return;\n", id="comparison"),
        pytest.param(
            "const f = ({ monthlyPrice }) => monthlyPrice;\n", id="destructuring and arrow"
        ),
        pytest.param("const p = a ? monthlyPrice : 0;\n", id="ternary"),
        pytest.param("const monthlyPrice = row.monthlyPrice;\n", id="plain assignment"),
        pytest.param("const { monthlyPrice, setupFee } = row;\n", id="destructuring"),
        pytest.param('if (row["monthlyPrice"] === null) return;\n', id="subscript compared"),
        pytest.param('import * as prices from "./monthlyPrice";\n', id="namespace import"),
    ],
)
def test_ignores_typescript_that_is_not_price_arithmetic(source: str) -> None:
    assert typescript_violations(Path("x.ts"), source) == []


def test_scans_nested_folders_and_skips_the_exempt_file(tmp_path: Path) -> None:
    nested = tmp_path / "src" / "mihenk" / "deep" / "deeper"
    nested.mkdir(parents=True)
    (nested / "bad.py").write_text("x = renewal_price - 1\n", encoding="utf-8")
    exempt = tmp_path / "src" / "mihenk" / "verify"
    exempt.mkdir(parents=True)
    (exempt / "checks.py").write_text("ratio = annual_total / monthly_price\n", encoding="utf-8")
    found = scan(tmp_path)
    assert [v.path.name for v in found] == ["bad.py"]
