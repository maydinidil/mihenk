# Stage 0 record

Date: 2026-10-09. Branch: `stage-0`. Plan: `docs/superpowers/plans/2026-10-08-mihenk-stages-0-1.md`.

Stage 0 builds the foundation: the repository, the local server and its guard, the screens
skeleton, the launcher, the browser driver, the repository checks, packaging and CI. Each task
was built by one agent and reviewed once by another; review findings rated Important were fixed
once, and smaller ones were collected and fixed together at the end of the stage.

## State at the end of the stage

| Item | State |
|---|---|
| Tasks 0.1 to 0.10 | Done on this machine |
| Task 0.11 (the private record points here) | Done outside this repository |
| GitHub repository | Not created yet; nothing pushed |
| CI (`ci.yml`, `build.yml`) | Written and reviewed; never run. Waits for the first push |
| Windows build | Frozen app built and release-checked here (35 MiB, 112 files, smoke exit 0) |
| Windows installer, macOS build and disk image | Written; run in CI only |
| Tests | 247 Python tests and 34 screens tests pass; ruff, mypy, ESLint and the TypeScript check are clean |
| Final review (seams between tasks) | All eight seams hold; its smaller findings are listed below |

## Rulings made during the stage

| Ruling | Why |
|---|---|
| Missing Origin on a state-changing request is refused, even with `Sec-Fetch-Site: same-origin` | §14 says so explicitly |
| The guard is stricter than §14's text in two places: a GET with a foreign Origin is refused, and any `Sec-Fetch-Site` other than `same-origin` or `none` is refused | Both fail closed, and no legitimate caller of a 127.0.0.1 app sends them |
| `GuardConfig` refuses a token shorter than 32 characters or not ASCII, and a port outside 1 to 65535 | The guard must fail closed (§14) |
| uvicorn runs with `proxy_headers=False` and `log_config=None` | Every caller is on 127.0.0.1, so forwarded headers cannot be trusted; uvicorn's own log config crashes the windowed build and hides server errors from `mihenk.log` |
| Every response carries a Content-Security-Policy (`default-src 'self'` and tighter) | The screens load nothing from elsewhere |
| The test guard also blocks asyncio connections on Windows, and name lookups for anything but `localhost` | Tests never leave the machine |
| TypeScript pinned to 5.9 | TypeScript 7 conflicts with the lint and API-type tools in use |
| `httpx2` added for Starlette's test client (decision 0002) | Starlette 1.7 asks for it |
| The licence check reads production npm packages only | Build-only packages never ship |
| `pythonnet` 3.2.1 and `clr_loader` 0.3.1 pinned on Windows | The plan pins the pair the release check passed with |
| The frozen app leaves out `mypy` and `setuptools` | They were pulled in by `pydantic.mypy` and cffi's build shim, never run, and were not in the notices |
| The notices include the Python runtime's licence | The frozen app embeds CPython |
| Release checks run here used a temporary data folder | The real user profile stays untouched until Aydin's own check |
| The Microsoft Store is not used before 1.0 (proposed, decision 0005) | It needs a second release pipeline and changes to the Windows build |

## Carried forward

| Item | Where it goes |
|---|---|
| The TypeScript price-arithmetic lint misses a price name inside a regex literal or JSX text line, and a price name that is not a call's last argument | Stage 2, when price fields first exist; an ESLint rule may replace the regex |
| `packaging/mihenk.spec` is not linted by ruff | Not fixed: it is PyInstaller's own file format |
| Playwright is not in the frozen build yet | Stage 1, when capture is wired into the app |
| `choco install innosetup` and `setup-uv` versions are not pinned in CI | After the first CI run |
| The licence metadata of the macOS-only packages (pyobjc) | Checked by the first macOS CI run |
| `pythonnet` 3.2.1 was one day old when pinned | Re-check for a yank or regression before the first release |
| The launcher's token filter redacts log messages but not traceback text, and sits on the `pywebview` logger only | Stage 1 small-fixes batch: move it to the log file's handler and redact `exc_text` |
| The test guard does not cover `gethostbyname`, `gethostbyaddr`, `getnameinfo` or UDP `sendto` | Stage 1 small-fixes batch |
| The notices generator ignores environment markers, while the licence check honours them | Stage 1 small-fixes batch: share the check's marker rule |
| The licence check imports `packaging`, which arrives only through other dev tools | Stage 1 small-fixes batch: name it in the dev group |

## Waiting for Aydin

| Item | Note |
|---|---|
| Create the GitHub repository `maydinidil/mihenk` | Then the remote is added and the first push needs Aydin's go |
| Licence texts that the installed packages do not ship: the WebView2 SDK (bundled by pywebview) and `proxy-tools` | Needs a one-time download of the two licence files |
| Decision 0005, Microsoft Store | Before 1.0 |
| Hand checks: the window opens and closing it ends the app; `--smoke` with the default data folder | On Aydin's machine |
| Open the stage-0 pull request | After CI is green |
