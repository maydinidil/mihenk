# Build from the repository root: uv run pyinstaller packaging/mihenk.spec --noconfirm
import os
import sys

from PyInstaller.utils.hooks import collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 (SPECPATH is set by PyInstaller)
sys.path.insert(0, os.path.join(ROOT, "src"))
from mihenk import __version__  # noqa: E402

datas = collect_data_files("mihenk", includes=["web_dist/**"])
datas += [(os.path.join(ROOT, name), ".") for name in ("LICENSE", "NOTICE", "EVALUATION.md", "THIRD_PARTY_NOTICES.txt")]

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "src", "mihenk", "__main__.py")],
    pathex=[os.path.join(ROOT, "src")],
    datas=datas,
    # pywebview would otherwise pull in every GUI backend it finds; Qt is GPL (§18).
    # pydantic.mypy drags in the dev-only type checker and cffi's build shim drags in
    # setuptools; neither runs in the app, and neither is in the notices.
    excludes=["PyQt5", "PyQt6", "PySide2", "PySide6", "qtpy", "gi", "tkinter",
              "mypy", "mypy_extensions", "pydantic.mypy", "setuptools"],
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz, a.scripts, [], exclude_binaries=True, name="mihenk",
    console=False, upx=False, codesign_identity=None,
    # A crash must end the process, not wait on an error dialog (CI would hang).
    disable_windowed_traceback=True,
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="mihenk")  # noqa: F821
if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll, name="mihenk.app", bundle_identifier="io.github.maydinidil.mihenk",
        info_plist={"CFBundleShortVersionString": __version__, "NSHighResolutionCapable": True},
    )
