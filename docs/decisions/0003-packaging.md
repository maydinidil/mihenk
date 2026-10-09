# 0003: Packaging with PyInstaller, Inno Setup and a disk image

Date: 2026-10-09. Status: Windows build decided and checked on this machine. The Windows
installer, the macOS build and the disk image are written and wait for CI.

## The question

How does mihenk reach a user who has no Python? The design (§17) says a PyInstaller onedir build
on both systems, an Inno Setup installer on Windows and a disk image on macOS.

## What was built

| File | What it is |
|---|---|
| `packaging/mihenk.spec` | The PyInstaller spec. Onedir, windowed, no UPX. It bundles the built screens, `LICENSE`, `NOTICE`, `EVALUATION.md` and `THIRD_PARTY_NOTICES.txt`. It leaves out the Qt, GTK and Tk libraries, so pywebview can only pick the Windows or macOS backend. It also leaves out `mypy`, `mypy_extensions`, `pydantic.mypy` and `setuptools`: `pydantic.mypy` pulled in the dev-only type checker and cffi's build shim pulled in setuptools, neither runs in the app, and neither was in the notices. That exclusion is the one change from the spec the task gave. On macOS it also wraps the folder in `mihenk.app`. |
| `packaging/windows/mihenk.iss` | The Inno Setup 6 script. Per-user install under `%LOCALAPPDATA%\Programs\mihenk`, no administrator rights. It installs Microsoft WebView2 first when the machine has none. |
| `packaging/macos/make_dmg.sh` | One `hdiutil create` call that turns `dist/mihenk.app` into `dist/mihenk-<version>-macos-arm64.dmg`. |
| `tools/gen_notices.py` | One new part: the licence text of the Python runtime (PSF-2.0), because the frozen app embeds CPython. See below. |
| `pyproject.toml`, `uv.lock` | Two Windows-only pins, `pythonnet==3.2.1` and `clr_loader==0.3.1`. See below. |

The `AppId` in the Inno Setup script was generated once for mihenk. It must never change, or
Windows treats a later version as a different app.

## What was checked on this machine (Windows 11 x64)

| Check | Result |
|---|---|
| `cd web && npm run build`, then `uv run python tools/gen_notices.py` | Pass |
| `uv run pyinstaller packaging/mihenk.spec --noconfirm` | Pass, about 26 seconds |
| Size of `dist/mihenk/` | 35 MiB in 112 files (38.8 MiB in 188 files before the dev packages were excluded) |
| Screens, licence files and notices inside `dist/mihenk/_internal/` | Present |
| Qt, GTK or Tk libraries in the build | None |
| Dev-only packages in the build (`mypy`, `setuptools`, `ast_serialize`, `librt`) | None, after the exclusion above |
| Release check on the unpacked build, `mihenk.exe --smoke --data-dir <temporary folder>` | Exit code 0 in 4.3 seconds. The log shows the server start. |
| Same check with `--smoke-timeout 0.05`, to prove the exit code can fail | Exit code 1 |
| Release check again after the pythonnet pin and a rebuild | Exit code 0 in 4.1 seconds |
| Release check again after excluding the dev packages and a rebuild | Exit code 0 in 3.9 seconds |

The release check ran with its data folder outside the real user profile.

### The pythonnet pin

pywebview does not pin `pythonnet`, and a brand-new release can break the .NET loader (§17).
`uv.lock` resolved `pythonnet` 3.2.1 and `clr_loader` 0.3.1, and the release check passed with
that pair. Both are now pinned exactly in `dependencies`, guarded by `sys_platform == 'win32'`.
`uv lock` changed only mihenk's own metadata: no other package moved.

### The Python runtime notice

The frozen app carries its own CPython, and `THIRD_PARTY_NOTICES.txt` had no section for it.
`gen_notices.py` now adds one, headed `Python <version> (PSF-2.0)`, with the text of
`LICENSE.txt` from the Python install the build ran with. If no licence file is found, the
generator prints a WARNING like it does for every other part. Unix builds keep the file in the
standard library folder, so the generator looks there too. That Unix path is covered by a unit
test but has not run on a real macOS build.

## What is pending CI

CI is Task 0.9 and starts only after Aydin's go to push.

| Step | Needs | Status |
|---|---|---|
| Step 1, macOS half: build `dist/mihenk.app`, then `dist/mihenk.app/Contents/MacOS/mihenk --smoke` must exit 0 | macOS | Pending CI |
| Step 2, macOS spike. If the PyInstaller build fails the release check, try in order: (a) spec changes (hidden imports for `webview.platforms.cocoa`, pyobjc frameworks), (b) py2app, (c) Nuitka after reading its `LICENSE-RUNTIME.txt`. Record the error output of each failed attempt and the chosen tool here. A change of tool goes to Aydin before stage 1 starts. | macOS | Pending CI. Nothing was tried. |
| Step 3, Windows installer: download the WebView2 bootstrapper from `https://go.microsoft.com/fwlink/p/?LinkId=2124703` into `packaging/windows/` (git-ignored), compile with `iscc /DAppVersion=0.0.1 packaging\windows\mihenk.iss`, install silently with `/VERYSILENT /SUPPRESSMSGBOXES`, then run `%LOCALAPPDATA%\Programs\mihenk\mihenk.exe --smoke` (exit 0) | Inno Setup, a download, a real install | Pending CI. The script is written but has never been compiled. |
| Step 3, record the Inno Setup version and its licence here. `ArchitecturesAllowed=x64compatible` needs Inno Setup 6.3 or newer | Inno Setup | Pending CI |
| Step 4, disk image: `sh packaging/macos/make_dmg.sh 0.0.1` produces a `.dmg` that mounts | macOS | Pending CI |

Nothing was installed or downloaded on this machine for these steps.

## Not decided here

Code signing and notarisation are not part of this task. The design (§17) ships an unsigned beta
first and signs before 1.0. Until then, Windows shows a SmartScreen warning (and Smart App
Control blocks the app where it is on), and macOS needs Open Anyway in System Settings.
