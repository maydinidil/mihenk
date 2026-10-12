"""The wheel build hook (hatch_build.py), run without hatchling: only its base class is stubbed."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
INTERFACE = "hatchling.builders.hooks.plugin.interface"


class _FakeBuildHookInterface:
    def __init__(self, root: str) -> None:
        self.root = root


@pytest.fixture
def hook_class(monkeypatch: pytest.MonkeyPatch) -> Any:
    parts = INTERFACE.split(".")
    for end in range(1, len(parts) + 1):
        monkeypatch.setitem(sys.modules, ".".join(parts[:end]), ModuleType(".".join(parts[:end])))
    sys.modules[INTERFACE].BuildHookInterface = _FakeBuildHookInterface
    spec = importlib.util.spec_from_file_location("mihenk_hatch_build", ROOT / "hatch_build.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.WebBuildHook


def _project(root: Path, *, index: bool, notices: bool) -> None:
    if index:
        web_dist = root / "src" / "mihenk" / "web_dist"
        web_dist.mkdir(parents=True)
        (web_dist / "index.html").write_text("<html></html>", encoding="utf-8")
    if notices:
        (root / "THIRD_PARTY_NOTICES.txt").write_text("notices", encoding="utf-8")


def test_skipping_the_screens_build_still_requires_index_html(
    hook_class: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MIHENK_SKIP_WEB_BUILD", "1")
    _project(tmp_path, index=False, notices=True)
    with pytest.raises(RuntimeError, match=r"the screens build produced no index\.html"):
        hook_class(str(tmp_path)).initialize("standard", {"force_include": {}})


def test_skipping_the_screens_build_with_built_screens_adds_the_notices(
    hook_class: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MIHENK_SKIP_WEB_BUILD", "1")
    _project(tmp_path, index=True, notices=True)
    build_data: dict[str, Any] = {"force_include": {}}
    hook_class(str(tmp_path)).initialize("standard", build_data)
    assert build_data["force_include"] == {
        str(tmp_path / "THIRD_PARTY_NOTICES.txt"): "mihenk/THIRD_PARTY_NOTICES.txt"
    }


def test_the_wheel_build_still_requires_the_notices(
    hook_class: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MIHENK_SKIP_WEB_BUILD", "1")
    _project(tmp_path, index=True, notices=False)
    with pytest.raises(RuntimeError, match=r"run tools/gen_notices\.py"):
        hook_class(str(tmp_path)).initialize("standard", {"force_include": {}})


def test_without_the_skip_variable_the_screens_are_built(
    hook_class: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MIHENK_SKIP_WEB_BUILD", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)  # no npm: the build step must be reached
    _project(tmp_path, index=True, notices=True)
    with pytest.raises(RuntimeError, match="npm is needed"):
        hook_class(str(tmp_path)).initialize("standard", {"force_include": {}})


def test_an_editable_install_needs_neither_screens_nor_notices(
    hook_class: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MIHENK_SKIP_WEB_BUILD", "1")
    build_data: dict[str, Any] = {"force_include": {}}
    hook_class(str(tmp_path)).initialize("editable", build_data)
    assert build_data == {"force_include": {}}
