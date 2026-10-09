import json
from pathlib import Path

import pytest
from packaging.requirements import Requirement

from tools import check_licenses
from tools.check_licenses import (
    ALLOWED,
    Override,
    load_overrides,
    parse_requirements,
    python_expression,
    spdx_allowed,
)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("MIT", True),
        ("Apache-2.0", True),
        ("MIT OR GPL-3.0-only", True),
        ("MIT AND GPL-3.0-only", False),
        ("(MIT OR Apache-2.0) AND BSD-3-Clause", True),
        ("LGPL-2.1-or-later", False),
        ("GPL-2.0-or-later WITH Classpath-exception-2.0", False),
        ("MPL-2.0", True),
        ("LicenseRef-Proprietary", False),
    ],
)
def test_spdx_expressions(expression: str, expected: bool) -> None:
    assert spdx_allowed(expression, ALLOWED) is expected


def test_malformed_expression_is_an_error() -> None:
    with pytest.raises(ValueError, match="licence expression"):
        spdx_allowed("MIT OR", ALLOWED)


@pytest.mark.parametrize(
    "expression",
    [
        pytest.param("MIT?", id="an unknown character is not dropped"),
        pytest.param("MIT/Apache-2.0", id="a slash is not an operator"),
        pytest.param("MIT, Apache-2.0", id="a comma"),
        pytest.param("MIT OR OR", id="OR is not a licence id"),
        pytest.param("MIT AND AND", id="AND is not a licence id"),
        pytest.param("AND", id="a lone operator"),
        pytest.param("OR MIT", id="starts with an operator"),
        pytest.param("MIT WITH", id="WITH without an exception"),
        pytest.param("MIT WITH OR", id="WITH followed by an operator"),
        pytest.param("MIT WITH (", id="WITH followed by a bracket"),
        pytest.param("WITH", id="WITH is not a licence id"),
        pytest.param("MIT License", id="a free-text licence name"),
        pytest.param("SEE LICENSE IN LICENSE.md", id="npm's pointer to a file"),
        pytest.param("()", id="empty brackets"),
        pytest.param("", id="empty"),
    ],
)
def test_malformed_expressions_raise_instead_of_passing(expression: str) -> None:
    with pytest.raises(ValueError, match="licence expression"):
        spdx_allowed(expression, ALLOWED)


def test_operators_are_case_insensitive_as_before() -> None:
    assert spdx_allowed("MIT or GPL-3.0-only", ALLOWED) is True
    assert spdx_allowed("MIT and GPL-3.0-only", ALLOWED) is False


# --- installed metadata, with fake distributions found through sys.path ---------------------


def _install(root: Path, name: str, version: str, *headers: str) -> None:
    info = root / f"{name}-{version}.dist-info"
    info.mkdir()
    lines = ["Metadata-Version: 2.4", f"Name: {name}", f"Version: {version}", *headers]
    (info / "METADATA").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def site_packages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "site-packages"
    folder.mkdir()
    monkeypatch.syspath_prepend(str(folder))
    return folder


MIT_CLASSIFIER = "Classifier: License :: OSI Approved :: MIT License"
BSD_CLASSIFIER = "Classifier: License :: OSI Approved :: BSD License"
GPL_CLASSIFIER = "Classifier: License :: OSI Approved :: GNU General Public License v3 (GPLv3)"


def test_license_expression_metadata_comes_first(site_packages: Path) -> None:
    _install(site_packages, "zzexpr", "1.0", "License-Expression: Apache-2.0", MIT_CLASSIFIER)
    assert python_expression("zzexpr", {}) == "Apache-2.0"


def test_a_single_mapped_classifier_is_used(site_packages: Path) -> None:
    _install(site_packages, "zzclassifier", "1.0", MIT_CLASSIFIER)
    assert python_expression("zzclassifier", {}) == "MIT"


def test_non_licence_classifiers_are_ignored(site_packages: Path) -> None:
    _install(
        site_packages,
        "zzother",
        "1.0",
        "Classifier: Programming Language :: Python :: 3",
        MIT_CLASSIFIER,
        "Classifier: Operating System :: OS Independent",
    )
    assert python_expression("zzother", {}) == "MIT"


def test_a_package_with_an_unmapped_licence_classifier_is_unknown(site_packages: Path) -> None:
    # MIT is listed first; the GPL classifier must still make the whole package unknown.
    _install(site_packages, "zzmixed", "1.0", MIT_CLASSIFIER, GPL_CLASSIFIER)
    assert python_expression("zzmixed", {}) is None
    _install(site_packages, "zzmixedreverse", "1.0", GPL_CLASSIFIER, MIT_CLASSIFIER)
    assert python_expression("zzmixedreverse", {}) is None


def test_all_mapped_classifiers_still_resolve(site_packages: Path) -> None:
    _install(site_packages, "zzduo", "1.0", MIT_CLASSIFIER, BSD_CLASSIFIER)
    assert python_expression("zzduo", {}) == "MIT"


def test_a_package_that_states_no_licence_is_unknown(site_packages: Path) -> None:
    _install(site_packages, "zzsilent", "1.0")
    assert python_expression("zzsilent", {}) is None


def test_an_override_for_the_installed_version_is_used(site_packages: Path) -> None:
    _install(site_packages, "zzoverridden", "1.0")
    overrides = {"zzoverridden": Override(spdx="MIT", version="1.0")}
    assert python_expression("zzoverridden", overrides) == "MIT"


def test_an_override_for_another_version_is_unknown_again(site_packages: Path) -> None:
    _install(site_packages, "zzmoved", "2.0")
    overrides = {"zzmoved": Override(spdx="MIT", version="1.0")}
    assert python_expression("zzmoved", overrides) is None


def test_a_stale_override_does_not_hide_what_the_metadata_now_says(site_packages: Path) -> None:
    _install(site_packages, "zzmoved2", "2.0", "License-Expression: GPL-3.0-only")
    overrides = {"zzmoved2": Override(spdx="MIT", version="1.0")}
    assert python_expression("zzmoved2", overrides) == "GPL-3.0-only"


def test_overrides_are_loaded_with_their_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "license_overrides.toml").write_text(
        '[Some-Package]\nspdx = "MIT"\nversion = "1.2.3"\nsource = "somewhere"\n', encoding="utf-8"
    )
    monkeypatch.setattr(check_licenses, "ROOT", tmp_path)
    assert load_overrides() == {"some-package": Override(spdx="MIT", version="1.2.3")}


def test_an_override_without_a_version_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "license_overrides.toml").write_text(
        '[some-package]\nspdx = "MIT"\n', encoding="utf-8"
    )
    monkeypatch.setattr(check_licenses, "ROOT", tmp_path)
    with pytest.raises(ValueError, match=r"some-package.*version"):
        load_overrides()


def test_the_real_overrides_file_pins_a_version_for_every_entry() -> None:
    overrides = load_overrides()
    assert "clr-loader" in overrides
    assert all(entry.version for entry in overrides.values())


def test_requirements_keep_their_platform_markers() -> None:
    exported = (
        "# This file was autogenerated by uv\n"
        "annotated-doc==0.0.5\n"
        "    # via fastapi\n"
        "clr-loader==0.3.1 ; sys_platform == 'nowhere'\n"
        "\n"
        "-e .\n"
        "pycparser==3.1 ; implementation_name != 'PyPy' and sys_platform == 'nowhere'\n"
    )
    found = parse_requirements(exported)
    assert [r.name for r in found] == ["annotated-doc", "clr-loader", "pycparser"]
    assert found[0].marker is None
    assert found[1].marker is not None
    assert found[1].marker.evaluate() is False


# --- main() ---------------------------------------------------------------------------------


class Run:
    """One run of check_licenses.main() against fake inputs: no subprocess, no network."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = root
        self.monkeypatch = monkeypatch
        (root / "tools").mkdir(exist_ok=True)
        monkeypatch.setattr(check_licenses, "ROOT", root)
        self.overrides("")
        self.python()
        self.npm()

    def overrides(self, toml: str) -> None:
        (self.root / "tools" / "license_overrides.toml").write_text(toml, encoding="utf-8")

    def python(self, *requirements: str) -> None:
        parsed = [Requirement(r) for r in requirements]
        self.monkeypatch.setattr(check_licenses, "python_runtime_requirements", lambda: parsed)

    def npm(self, **licences: object) -> None:
        for name, value in licences.items():
            folder = self.root / "web" / "node_modules" / name
            folder.mkdir(parents=True)
            package = {} if value is None else {"license": value}
            (folder / "package.json").write_text(json.dumps(package), encoding="utf-8")
        self.monkeypatch.setattr(check_licenses, "npm_runtime_packages", lambda: list(licences))

    def main(self, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
        code = check_licenses.main()
        return code, capsys.readouterr().out


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, site_packages: Path) -> Run:
    return Run(tmp_path, monkeypatch)


def test_main_passes_when_every_licence_is_allowed(
    run: Run, site_packages: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _install(site_packages, "zzfine", "1.0", "License-Expression: MIT")
    run.python("zzfine==1.0")
    run.npm(**{"fine-pkg": "Apache-2.0"})
    code, out = run.main(capsys)
    assert (code, out) == (0, "")


def test_main_reports_a_python_package_on_a_disallowed_licence(
    run: Run, site_packages: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _install(site_packages, "zzcopyleft", "1.0", "License-Expression: GPL-3.0-only")
    run.python("zzcopyleft==1.0")
    code, out = run.main(capsys)
    assert code == 1
    assert "LICENCE PROBLEM python zzcopyleft: GPL-3.0-only" in out


def test_main_reports_a_python_package_whose_licence_is_unknown(
    run: Run, site_packages: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _install(site_packages, "zzsilent2", "1.0", MIT_CLASSIFIER, GPL_CLASSIFIER)
    run.python("zzsilent2==1.0")
    code, out = run.main(capsys)
    assert code == 1
    assert "LICENCE PROBLEM python zzsilent2: licence unknown" in out


def test_main_reports_an_unreadable_python_expression_and_carries_on(
    run: Run, site_packages: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _install(site_packages, "zzodd", "1.0", "License-Expression: MIT License")
    _install(site_packages, "zzgpl", "1.0", "License-Expression: GPL-3.0-only")
    run.python("zzodd==1.0", "zzgpl==1.0")
    code, out = run.main(capsys)
    assert code == 1
    assert "LICENCE PROBLEM python zzodd:" in out
    assert "LICENCE PROBLEM python zzgpl: GPL-3.0-only" in out


def test_main_uses_an_override_for_the_installed_version(
    run: Run, site_packages: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _install(site_packages, "zzbare", "1.0")
    run.overrides('[zzbare]\nspdx = "MIT"\nversion = "1.0"\nsource = "read the file"\n')
    run.python("zzbare==1.0")
    assert run.main(capsys) == (0, "")


def test_main_rechecks_a_package_whose_override_is_for_another_version(
    run: Run, site_packages: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _install(site_packages, "zzbare2", "2.0")
    run.overrides('[zzbare2]\nspdx = "MIT"\nversion = "1.0"\nsource = "read the file"\n')
    run.python("zzbare2==2.0")
    code, out = run.main(capsys)
    assert code == 1
    assert "LICENCE PROBLEM python zzbare2: licence unknown" in out
    assert "lists version 1.0 but 2.0 is installed" in out


def test_main_lets_an_approved_lgpl_package_through(
    run: Run, site_packages: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _install(site_packages, "zzlgpl", "1.0", "License-Expression: LGPL-3.0-or-later")
    run.python("zzlgpl==1.0")
    assert run.main(capsys)[0] == 1
    run.monkeypatch.setattr(check_licenses, "APPROVED_LGPL", frozenset({"zzlgpl"}))
    assert run.main(capsys) == (0, "")


def test_main_skips_a_missing_package_that_belongs_to_another_platform(
    run: Run, capsys: pytest.CaptureFixture[str]
) -> None:
    run.python("zzothersystem==1.0 ; sys_platform == 'nowhere'")
    code, out = run.main(capsys)
    assert code == 0
    assert "skip zzothersystem" in out


@pytest.mark.parametrize(
    "requirement",
    [
        pytest.param("zzabsent==1.0", id="no marker"),
        pytest.param("zzabsent==1.0 ; python_version >= '3'", id="a marker that is true here"),
    ],
)
def test_main_reports_a_missing_package_this_platform_needs(
    run: Run, capsys: pytest.CaptureFixture[str], requirement: str
) -> None:
    run.python(requirement)
    code, out = run.main(capsys)
    assert code == 1
    assert "LICENCE PROBLEM python zzabsent: not installed" in out
    assert "skip" not in out


def test_main_reports_a_non_spdx_npm_licence_and_carries_on(
    run: Run, capsys: pytest.CaptureFixture[str]
) -> None:
    run.python()
    run.npm(
        **{
            "odd-name": "MIT License",
            "pointer": "SEE LICENSE IN LICENSE.md",
            "copyleft": "GPL-3.0-only",
            "fine": "MIT",
        }
    )
    code, out = run.main(capsys)
    assert code == 1
    assert "LICENCE PROBLEM npm odd-name:" in out
    assert "LICENCE PROBLEM npm pointer:" in out
    assert "LICENCE PROBLEM npm copyleft: 'GPL-3.0-only'" in out
    assert "npm fine" not in out


def test_main_reports_an_npm_package_without_a_licence_string(
    run: Run, capsys: pytest.CaptureFixture[str]
) -> None:
    run.python()
    run.npm(nolicence=None, objectform={"type": "MIT"})
    code, out = run.main(capsys)
    assert code == 1
    assert "LICENCE PROBLEM npm nolicence: None" in out
    assert "LICENCE PROBLEM npm objectform:" in out
