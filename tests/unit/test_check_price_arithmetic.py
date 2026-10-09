from pathlib import Path

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


def test_scans_nested_folders_and_skips_the_exempt_file(tmp_path: Path) -> None:
    nested = tmp_path / "src" / "mihenk" / "deep" / "deeper"
    nested.mkdir(parents=True)
    (nested / "bad.py").write_text("x = renewal_price - 1\n", encoding="utf-8")
    exempt = tmp_path / "src" / "mihenk" / "verify"
    exempt.mkdir(parents=True)
    (exempt / "checks.py").write_text("ratio = annual_total / monthly_price\n", encoding="utf-8")
    found = scan(tmp_path)
    assert [v.path.name for v in found] == ["bad.py"]
