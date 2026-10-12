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


@pytest.mark.parametrize(
    ("source", "field"),
    [
        pytest.param('x = Decimal(row["monthly_price"]) / 12\n', "monthly_price", id="Decimal()"),
        pytest.param("x = float(plan.monthly_price) * 12\n", "monthly_price", id="float()"),
        pytest.param("x = -monthly_price * 2\n", "monthly_price", id="unary minus"),
        pytest.param("x = round(x.monthly_price, 2) + 1\n", "monthly_price", id="round()"),
        pytest.param('x = row.get("monthly_price") + 1\n', "monthly_price", id=".get()"),
        pytest.param('x = row.get("setup_fee", 0) - 1\n', "setup_fee", id=".get() with a default"),
        pytest.param('x = getattr(plan, "renewal_price") * 2\n', "renewal_price", id="getattr()"),
        pytest.param(
            "x = 12 * Decimal(plan.annual_total)\n", "annual_total", id="price on the right"
        ),
        pytest.param("x = sum(p.unit_amount for p in plans) + 1\n", "unit_amount", id="generator"),
        pytest.param("x = (plan.flat_amount.quantize(q)) / 2\n", "flat_amount", id="method chain"),
        pytest.param(
            "total += Decimal(row.promo_price)\n", "promo_price", id="augmented, in a call"
        ),
        pytest.param(
            'label = "a" + str(row["annual_total"] * 2)\n',
            "annual_total",
            id="arithmetic inside a string concatenation",
        ),
    ],
)
def test_flags_price_fields_anywhere_in_the_operand(source: str, field: str) -> None:
    found = python_violations(Path("x.py"), source)
    assert {v.field for v in found} == {field}


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('x = "%s" % monthly_price\n', id="percent formatting"),
        pytest.param('x = "%s: %s" % (name, row["monthly_price"])\n', id="percent with a tuple"),
        pytest.param('x = "a" + monthly_price\n', id="constant on the left of a plus"),
        pytest.param('x = monthly_price + "a"\n', id="constant on the right of a plus"),
        pytest.param('x = "Plan " + plan.name + ": " + str(plan.monthly_price)\n', id="chain"),
        pytest.param('x = plan.name + ": " + str(plan.monthly_price)\n', id="chain from a name"),
        pytest.param('x = f"{monthly_price}" + "!"\n', id="f-string plus a constant"),
        pytest.param('x = f"price: {monthly_price}" + suffix\n', id="f-string plus a name"),
        pytest.param('x = suffix + f"{plan.monthly_price}"\n', id="a name plus an f-string"),
        pytest.param('x = "%s" % str(plan.monthly_price)\n', id="percent with str()"),
        pytest.param('text += f"{plan.monthly_price}"\n', id="augmented, f-string"),
        pytest.param('text += "x" + str(plan.monthly_price)\n', id="augmented, a concatenation"),
        pytest.param("text += str(plan.monthly_price)\n", id="augmented, str()"),
        pytest.param('FIELDS = ["monthly_price"] + extra\n', id="a list of field names"),
        pytest.param('x = row["name"] + "monthly_price"\n', id="the name only as text"),
        pytest.param("x = monthly_price\n", id="plain assignment"),
        pytest.param("x = monthly_price == other\n", id="comparison"),
    ],
)
def test_ignores_string_formatting_and_concatenation(source: str) -> None:
    assert python_violations(Path("x.py"), source) == []


def test_a_price_expression_is_reported_once_per_line_and_field() -> None:
    found = python_violations(Path("x.py"), "x = a * monthly_price + b - monthly_price\n")
    assert [(v.line, v.field) for v in found] == [(1, "monthly_price")]


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
