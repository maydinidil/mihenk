# mihenk Stages 0 and 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up mihenk's public repository with an installable, security-checked desktop shell on Windows and macOS (stage 0), then capture pricing pages by every method into auditable snapshots, with no LLM yet (stage 1).

**Architecture:** One Python process. pywebview owns the main thread and shows the React screens; a FastAPI app runs under uvicorn in a background thread on `127.0.0.1`, behind a guard that checks Host, Origin and a per-launch token before any route. Capture runs fetch (httpx2) or Playwright (installed Chrome or Edge) and writes immutable snapshot folders. Stage 1 is driven from a CLI; the screens for runs come in stage 3.

**Tech Stack:** Python 3.13, uv, hatchling, FastAPI 0.143, Starlette 1.7, uvicorn 0.54, pywebview 6.2.1, Playwright 1.63, protego 0.7, BeautifulSoup 4, httpx2, platformdirs 4.12, pytest, mypy (strict), ruff; React 19 + TypeScript (strict) + Vite 8, Vitest, ESLint, openapi-typescript 7.13; PyInstaller 6.22.3 (onedir); Inno Setup (Windows installer); hdiutil (macOS disk image); GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-08-mihenk-design.md` (sections cited as §N). Read it before any task.

## Where this plan runs

Task 0.1 creates the public repository `maydinidil/mihenk` and clones it to `C:\mihenk` (a path with no spaces). **Every later task runs in that clone**, on a branch per stage (`stage-0`, `stage-1`). Paths below are relative to its root. Task 0.11 is done outside this repository.

## Global Constraints

- Python `>=3.13,<3.14`, pinned in `.python-version` and `pyproject.toml`; one locked workflow: `uv` with a committed `uv.lock`. Screens: `npm` with a committed `package-lock.json`, Node 24 for building only.
- Dependency floors from the spec: `fastapi>=0.143.0`, `pyinstaller>=6.22.3`, `protego>=0.7.0`, `pywebview` 6.2.x installed **without extras**. Installing the dependencies named in this plan is approved with the plan; any other dependency needs Aydin.
- Licence: `PolyForm-Noncommercial-1.0.0` (SPDX) with `NOTICE` holding `Required Notice: Copyright 2026 maydinidil (https://github.com/maydinidil)`. No GPL or AGPL dependency; LGPL only with Aydin's approval (§18).
- Network: the app talks only to tracked pages, the chosen LLM provider and the update check (§14). FastAPI's `/docs`, `/redoc` and `/openapi.json` routes are off. No IP or geo lookup: the collection country is declared by the user (§10).
- Tests never leave the machine: a guard allows only loopback connections. No test visits a vendor site. Live captures happen only when Aydin runs the CLI.
- Local server: binds `127.0.0.1` only; `LocalOnlyGuard` (Task 0.3) wraps the whole app. Never add a development bypass.
- Playwright is driven through its sync API from one thread only (§5).
- No browser is bundled. Order: installed Chrome, installed Edge, then Playwright's Chromium only after the user agrees (§17).
- PyInstaller: onedir, never onefile; no UPX (§17). Vite's `build.outDir` is `src/mihenk/web_dist` (not `dist`).
- Money and prices: no arithmetic on price fields anywhere except `src/mihenk/verify/checks.py` (§4). Stage 1 has no price fields yet; the lint exists from stage 0.
- Snapshots are written once and never modified (§4, §7).
- Supported platforms: Windows 11 x64 and macOS 15+ on Apple silicon (§23).
- Test pages are our own words and markup; no vendor's real page is committed (§16).
- Commits go on the stage branch, as each task's last step says. **Pushing, pull requests and releases need Aydin's go each time.**
- Before every commit: `uv run ruff format .`, then `uv run ruff check --fix .`, then the task's own checks. Plan code that still fails lint is fixed the way ruff suggests, without renaming a public name or changing behaviour; a false positive gets an inline `# noqa: <code>` with a short reason.
- Nothing is installed globally and nothing is installed on this machine outside the repository and the `uv`/`npm` caches. A step that would install the app itself (an installer, `uv tool install`) runs in CI, or with its install folders pointed at a temporary directory.
- Docs written for Aydin: plain English, tables, no em dashes, no gendered pronouns.

## Review Focus

Input classes the spec implies but no requirement names, most likely to hurt a real user first. Each has a test in the task that owns the code.

1. **A pricing page that never goes network-idle** (trackers, polling, open connections): rendering must still finish within its time cap and capture the page. Test: `test_render_finishes_on_never_idle_page` (Task 1.8).
2. **Pages in a legacy encoding or with a wrong charset declaration, including Turkish text**: text must decode correctly and Turkish letters (ı, ş, ğ, İ) must survive byte-exact into `text.txt`. Tests: `test_decode_windows_1254_from_meta` (Task 1.4), `test_turkish_text_survives_snapshot` (Task 1.7).
3. **Very large pages and very large embedded JSON**: capture must finish, mark the oversize part, and never truncate silently. Tests: `test_page_over_size_cap_fails_as_too_large` (Task 1.4), `test_huge_json_block_is_marked_too_large` (Task 1.5).
4. **A `robots.txt` that is really an HTML page served with 200, or that redirects in a loop**: the first means "no rules" (allowed), the second is treated as unreachable (disallowed). Tests: `test_html_soft_404_robots_allows` (Task 1.2), `test_robots_redirect_loop_disallows` (Task 1.4).
5. **A Windows user folder with spaces and non-ASCII letters** (for example `C:\Users\Ayşe Yılmaz`): the app starts and snapshots are written. Tests: `test_data_dir_override_with_spaces_and_turkish_letters` (Task 0.5), `test_snapshot_in_path_with_spaces_and_turkish_letters` (Task 1.7).

---

## File structure

```
mihenk/                              (the public repository root)
  LICENSE  NOTICE  EVALUATION.md  README.md  CLAUDE.md  CHANGELOG.md
  pyproject.toml  uv.lock  .python-version  .gitignore  hatch_build.py
  docs/
    superpowers/specs/2026-10-08-mihenk-design.md      (public copy)
    superpowers/plans/2026-10-08-mihenk-stages-0-1.md   (this plan)
    decisions/NNNN-<topic>.md          (one per decision taken during the build, numbered in the order written; 0001 is the name)
  src/mihenk/
    __init__.py                      __version__
    __main__.py                      python -m mihenk
    cli.py                           mihenk capture / install-browser (Task 1.9, 1.10)
    app/paths.py                     data folder (Task 0.5)
    app/launcher.py                  server thread, window, smoke mode (Task 0.5)
    api/security.py                  LocalOnlyGuard (Task 0.3)
    api/server.py                    create_app (Task 0.3)
    api/routes/health.py             GET /api/health (Task 0.3)
    api/routes/smoke.py              POST /api/smoke/ok (Task 0.3)
    capture/browser.py               launch_browser, start_playwright, install_chromium (Task 0.6, 1.10)
    capture/models.py                Method, CaptureStatus (Task 1.4)
    capture/robots.py                robots.txt decisions (Task 1.2)
    capture/pace.py                  per-site pacing (Task 1.3)
    capture/fetch.py                 HTTP fetch and decoding (Task 1.4)
    capture/locale.py                locale markers (Task 1.6)
    capture/snapshot.py              snapshot writer (Task 1.7)
    capture/recipe.py                recipes and states (Task 1.8)
    capture/render.py                browser rendering (Task 1.8)
    capture/walls.py                 bot-wall detection (Task 1.9)
    capture/run.py                   capture_page orchestration (Task 1.9)
    trim/text.py                     canonical text, HTML to text (Task 1.5)
    trim/structured.py               JSON-LD and framework data (Task 1.5)
    web_dist/                        built screens (generated, ignored by git)
  web/                               React screens (Task 0.4)
  tools/
    dump_openapi.py  check_licenses.py  gen_notices.py  check_price_arithmetic.py
  packaging/
    mihenk.spec  windows/mihenk.iss  macos/make_dmg.sh
  tests/
    conftest.py                      network guard, shared fixtures
    helpers/site.py                  LocalSite test web server
    fixtures/pages/<name>/page.html + expect.json
    unit/...  integration/...
  .github/workflows/ci.yml  .github/workflows/build.yml
```

---

## Stage 0: skeleton and shipping

Done when (§21): an empty app window, served by FastAPI with the security guard, opens from an installer built in CI on Windows and macOS and drives the installed Chrome once; the four spikes are settled and recorded.

### Task 0.1: Name check and the public repository (needs Aydin)

**Files:** none in a repository yet. Produces `docs/decisions/0001-name-and-repository.md` in Task 0.2.

**Interfaces:** Produces the clone at `C:\mihenk` on branch `stage-0`.

- [x] **Step 1: The name.** Done 2026-10-09. The first choice, karat25, was dropped after an EU register search found the word mark KARAT registered for software (classes 9 and 42). Aydin chose mihenk and decided against a register search for it.
- [ ] **Step 2: Repository name check.** Confirm `https://github.com/maydinidil/mihenk` returns 404.
- [ ] **Step 3: Aydin creates the repository.** Ask Aydin to create an empty **public** repository `maydinidil/mihenk` (no README, licence or .gitignore: the next task adds them), or to approve running `gh repo create maydinidil/mihenk --public --description "Track competitors' pricing and packaging, every number checked against its source."`.
- [ ] **Step 4: Clone and branch.**

```bash
git clone https://github.com/maydinidil/mihenk.git C:/mihenk
cd C:/mihenk
git commit --allow-empty -m "Start mihenk"
git switch -c stage-0
```

Expected: `main` holds one empty commit, so the stage pull requests and the nightly build on `main` have a base; the working tree is on `stage-0`. `main` is pushed with the first push in Task 0.9, after Aydin's go. If the GitHub repository does not exist yet, run `git init -b main C:/mihenk` instead of the clone and add the remote (`git remote add origin https://github.com/maydinidil/mihenk.git`) once it exists.

### Task 0.2: Licence, public docs and the Python toolchain

**Files:**
- Create: `LICENSE`, `NOTICE`, `EVALUATION.md`, `README.md`, `CLAUDE.md`, `CHANGELOG.md`, `.gitignore`, `.python-version`, `pyproject.toml`, `src/mihenk/__init__.py`, `tests/unit/test_version.py`, `docs/decisions/0001-name-and-repository.md`, `docs/superpowers/specs/2026-10-08-mihenk-design.md`, `docs/superpowers/plans/2026-10-08-mihenk-stages-0-1.md`

**Interfaces:** Produces `mihenk.__version__: str` (`"0.0.1"`), the `uv` environment, and the check commands every later task runs.

- [ ] **Step 1: Licence files.** Download the official plain text of PolyForm Noncommercial 1.0.0 from `https://polyformproject.org/licenses/noncommercial/1.0.0.txt` into `LICENSE`, unmodified. Check its first line reads `# PolyForm Noncommercial License 1.0.0`. Create `NOTICE`:

```text
Required Notice: Copyright 2026 maydinidil (https://github.com/maydinidil)
```

Create `EVALUATION.md` (Aydin has been told a lawyer should check this wording before relying on it; §23):

```markdown
# Evaluation permission

In addition to the rights the PolyForm Noncommercial License 1.0.0 in `LICENSE` gives you,
maydinidil gives you permission to use mihenk for up to 30 days from your first use, including
at work or for a business, only to try it out and decide whether you want to keep using it or
to ask for a commercial licence. This permission does not let you use mihenk's results in
running a business beyond trying it out. All other terms of the licence still apply.

For a commercial licence, contact maydinidil through https://github.com/maydinidil.
```

- [ ] **Step 2: Public copies of the spec and this plan.** Copied from the private record, with every reference to private material removed.

- [ ] **Step 3: Toolchain files.** `.python-version`:

```text
3.13
```

`.gitignore`:

```gitignore
# Secrets: API keys never live in this repository
.env
.env.*
!.env.example
keys.json
*.key

# Build output and generated files
/src/mihenk/web_dist/
/build/
/dist/
/web/node_modules/
THIRD_PARTY_NOTICES.txt
# Microsoft's WebView2 bootstrapper, downloaded at build time (Task 0.8); never committed
packaging/windows/MicrosoftEdgeWebview2Setup.exe

# Python
.venv/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/

# Local run data (snapshots, logs, browsers) never goes in the repository
/runs/
/snapshots/
```

`pyproject.toml`:

```toml
[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[project]
name = "mihenk"
dynamic = ["version"]
description = "Track competitors' pricing and packaging, with every number checked against its source."
readme = "README.md"
license = "PolyForm-Noncommercial-1.0.0"
license-files = ["LICENSE", "NOTICE", "EVALUATION.md"]
requires-python = ">=3.13,<3.14"
dependencies = [
  "fastapi>=0.143.0,<0.144",
  "starlette>=1.7,<2",
  "uvicorn>=0.54,<0.55",
  "pywebview>=6.2.1,<6.3",
  "platformdirs>=4.12,<5",
  "playwright>=1.63,<1.64",
]

[project.scripts]
mihenk = "mihenk.app.launcher:main"

[dependency-groups]
dev = [
  "pytest>=8",
  "mypy>=1.10",
  "ruff>=0.5",
  "httpx>=0.28",
  "pyinstaller>=6.22.3",
]

[tool.hatch.version]
path = "src/mihenk/__init__.py"

[tool.hatch.build]
artifacts = ["src/mihenk/web_dist/"]

[tool.hatch.build.targets.wheel]
packages = ["src/mihenk"]

[tool.ruff]
line-length = 100
target-version = "py313"
src = [".", "src"]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "S", "N", "SIM", "RUF", "PTH", "DTZ"]
# N818: the plan's exception names (FetchFailure, BrowserUnavailable, ...) are shared
# interfaces between tasks. E501: the formatter owns line length; long strings may stay.
ignore = ["N818", "E501"]
# Turkish dotless i, typographic apostrophe and minus sign appear in test pages on purpose.
allowed-confusables = ["ı", "’", "−"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "S105", "S106", "S603", "S607", "N802"]
"tools/**" = ["S603", "S607"]
"hatch_build.py" = ["S603", "S607"]
"src/mihenk/capture/browser.py" = ["S603"]

[tool.mypy]
strict = true
python_version = "3.13"
mypy_path = "src"
packages = ["mihenk"]

[[tool.mypy.overrides]]
module = ["webview", "webview.*", "protego"]
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"
markers = [
  "browser: needs an installed Chrome or Edge",
]
```

The `[project.scripts]` entry point is created in Task 0.5; until then `mihenk` is not runnable, which is expected.

`src/mihenk/__init__.py`:

```python
"""mihenk: track competitors' pricing and packaging, every number checked against its source."""

__version__ = "0.0.1"
```

- [ ] **Step 4: Write the failing test.** `tests/unit/test_version.py`:

```python
import re

import mihenk


def test_version_is_semantic() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", mihenk.__version__)
```

- [ ] **Step 5: Install and run.**

Run: `uv sync` then `uv run pytest tests/unit/test_version.py -v`
Expected: PASS. If `uv sync` complains that `src/mihenk/web_dist/` is missing, create the empty folder and retry; git ignores it.

Run: `uv run ruff format --check . && uv run ruff check . && uv run mypy`
Expected: all pass.

- [ ] **Step 6: Public README, CLAUDE.md, CHANGELOG and the first decision record.**

`README.md`: what mihenk is (the first paragraph of the spec §1), the licence summary (PolyForm Noncommercial 1.0.0, source-available, the 30-day evaluation permission in `EVALUATION.md`), state ("stage 0, not usable yet"), and the check commands from `CLAUDE.md`.

`CLAUDE.md`:

```markdown
# mihenk: working rules

mihenk tracks competitors' pricing and packaging. It captures vendors' pricing pages, uses an
LLM through the user's own API key to extract plans, prices, limits and features, and checks
every number against a verbatim quote from the page. This file is for coding agents.

Read the design first: `docs/superpowers/specs/2026-10-08-mihenk-design.md`. Plans are in
`docs/superpowers/plans/`; decisions taken during the build are in `docs/decisions/`.

## Checks

| Check | Command |
|---|---|
| Python format and lint | `uv run ruff format --check . && uv run ruff check .` |
| Python types | `uv run mypy` |
| Python tests | `uv run pytest` |
| Screens | `cd web && npm run lint && npm run typecheck && npm test && npm run build` |
| API types up to date | `uv run python tools/dump_openapi.py && (cd web && npm run gen:api) && git diff --exit-code web/openapi.json web/src/api/schema.ts` |
| Licences | `uv run python tools/check_licenses.py` |
| No arithmetic on prices | `uv run python tools/check_price_arithmetic.py` |

Do not claim a check passed unless it ran.

## The method rules (design §4)

1. Never fabricate: a missing value is a correct answer, stored with a state saying why.
2. Never reconcile: no arithmetic that makes one number fit another.
3. Flag, don't fix: raw results are never changed; corrections are stored beside them.
4. Grounded extraction: every value carries a verbatim quote that code checks.
5. Provenance on every value.
6. Keep the distinctions apart: monthly vs annual, first-year vs renewal, promo vs list,
   per-seat vs flat, VAT included vs excluded.
7. Store the native currency.
8. Money is decimal, never float.
9. Collecting and analysing are separate layers.

## Non-negotiables

1. API keys never enter the repository: not in a committed `.env`, config, log, export,
   fixture, test or screenshot.
2. The app talks to three places only: the pages the user tracks, the LLM provider the user
   chose, and the update check. No telemetry, no accounts.
3. The local server binds `127.0.0.1`, and `LocalOnlyGuard` runs before every route. Never add
   a development bypass.
4. No GPL or AGPL dependency. LGPL only with Aydin's approval. pywebview without extras.
5. Snapshots and raw extractions are never edited.
6. Tests never reach the internet. Live vendor visits and paid LLM calls happen only when
   Aydin starts them.
7. Playwright is driven from one thread only.
8. No vendor's real pricing page is committed. Test pages are our own words and markup.

## Ask Aydin before

- Changing the approved design.
- Adding a dependency that no plan names.
- Pushing, opening a pull request, creating a release or publishing anything.
- Any live vendor visit or paid LLM call outside a step Aydin started.

## How to work with Aydin

- Put every pending decision in one batch, with a recommendation marked on each.
- Plans are goals and dates, never hours.
- Docs for Aydin: short, plain English, tables. No em dashes. No gendered pronouns.
```

`CHANGELOG.md`: Keep a Changelog header and an `## Unreleased` section with `### Added: the repository, licence, design and stage 0-1 plan`.

`docs/decisions/0001-name-and-repository.md`: the name (mihenk, chosen 2026-10-09: Turkish for touchstone, *mihenk taşı*, the stone used to test gold, and a word for benchmark), why the first choice karat25 was dropped (the EU word mark KARAT is registered for software in classes 9 and 42), that no register search was run for mihenk (Aydin's decision), the GitHub name check (free on 2026-10-09), and the repository URL.

- [ ] **Step 7: Commit.**

```bash
git add -A
git commit -m "Repository foundation: licence, design, plan, Python toolchain"
```

### Task 0.3: The local server and its guard

**Files:**
- Create: `src/mihenk/api/__init__.py`, `src/mihenk/api/security.py`, `src/mihenk/api/server.py`, `src/mihenk/api/routes/__init__.py`, `src/mihenk/api/routes/health.py`, `src/mihenk/api/routes/smoke.py`
- Test: `tests/unit/test_security.py`, `tests/unit/test_server.py`

**Interfaces:**
- Produces: `GuardConfig(port: int, token: str)`, `TOKEN_HEADER = "x-mihenk-token"`, `refusal_reason(config, method, path, headers) -> str | None`, `LocalOnlyGuard(app, config)`; `create_app(config: GuardConfig, web_dist: Path | None, smoke_signal: SmokeSignal | None = None) -> FastAPI`; `SmokeSignal` with `.event: threading.Event`; models `Health(status: Literal["ok"], version: str)` and `SmokeAck(received: bool)`.

- [ ] **Step 1: Write the failing guard tests.** `tests/unit/test_security.py`:

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from mihenk.api.security import TOKEN_HEADER, GuardConfig, LocalOnlyGuard

PORT = 51234
TOKEN = "test-token-0123456789abcdef"
BASE = f"http://127.0.0.1:{PORT}"
GOOD = {TOKEN_HEADER: TOKEN}


def make_client() -> TestClient:
    app = FastAPI()

    @app.get("/api/ping")
    def ping() -> dict[str, str]:
        return {"pong": "yes"}

    @app.post("/api/change")
    def change() -> dict[str, str]:
        return {"changed": "yes"}

    @app.get("/")
    def index() -> dict[str, str]:
        return {"page": "index"}

    app.add_middleware(LocalOnlyGuard, config=GuardConfig(port=PORT, token=TOKEN))
    return TestClient(app, base_url=BASE)


def test_api_get_with_token_passes() -> None:
    assert make_client().get("/api/ping", headers=GOOD).status_code == 200


def test_api_get_without_token_is_refused() -> None:
    response = make_client().get("/api/ping")
    assert response.status_code == 403
    assert response.text == "Refused: token"


def test_api_get_with_wrong_token_is_refused() -> None:
    response = make_client().get("/api/ping", headers={TOKEN_HEADER: "wrong"})
    assert response.status_code == 403


def test_non_ascii_token_is_refused_without_crashing() -> None:
    response = make_client().get("/api/ping", headers={TOKEN_HEADER: b"t\xf6ken"})
    assert response.status_code == 403


@pytest.mark.parametrize(
    "host",
    [f"evil.example:{PORT}", "127.0.0.1", "127.0.0.1:80", f"127.0.0.2:{PORT}", ""],
)
def test_wrong_host_is_refused(host: str) -> None:
    response = make_client().get("/api/ping", headers={**GOOD, "host": host})
    assert response.status_code == 403
    assert response.text == "Refused: host"


def test_localhost_host_passes() -> None:
    response = make_client().get("/api/ping", headers={**GOOD, "host": f"localhost:{PORT}"})
    assert response.status_code == 200


def test_index_needs_no_token() -> None:
    assert make_client().get("/").status_code == 200


def test_post_without_origin_is_refused() -> None:
    response = make_client().post("/api/change", headers=GOOD)
    assert response.status_code == 403
    assert response.text == "Refused: origin"


def test_post_from_own_origin_passes() -> None:
    response = make_client().post("/api/change", headers={**GOOD, "origin": BASE})
    assert response.status_code == 200


def test_post_with_same_origin_fetch_site_but_no_origin_is_refused() -> None:
    # Design §14: a missing Origin is accepted only on GET and HEAD.
    headers = {**GOOD, "sec-fetch-site": "same-origin"}
    response = make_client().post("/api/change", headers=headers)
    assert response.status_code == 403
    assert response.text == "Refused: origin"


def test_origin_on_another_port_is_refused() -> None:
    headers = {**GOOD, "origin": "http://127.0.0.1:9999"}
    assert make_client().post("/api/change", headers=headers).status_code == 403


@pytest.mark.parametrize("site", ["same-site", "cross-site"])
def test_other_sites_are_refused(site: str) -> None:
    response = make_client().get("/api/ping", headers={**GOOD, "sec-fetch-site": site})
    assert response.status_code == 403
    assert response.text == "Refused: fetch-site"


def test_websocket_is_refused() -> None:
    with pytest.raises(WebSocketDisconnect), make_client().websocket_connect("/ws"):
        pass
```

- [ ] **Step 2: Run them to see them fail.**

Run: `uv run pytest tests/unit/test_security.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mihenk.api'`.

- [ ] **Step 3: Write the guard.** `src/mihenk/api/security.py`:

```python
"""The local-only guard that runs before every route (design §14).

Three checks: the Host header names this server exactly, port included; a state-changing
request comes from this app's own origin; every /api/ request carries the token created at
launch. Anything else gets a 403 before any route runs. CORS is not a defence here: it hides
answers from other sites but still runs their requests.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

TOKEN_HEADER = "x-mihenk-token"
_SAFE_METHODS = frozenset({"GET", "HEAD"})
_TRUSTED_FETCH_SITES = frozenset({"same-origin", "none"})


@dataclass(frozen=True)
class GuardConfig:
    port: int
    token: str

    @property
    def allowed_hosts(self) -> frozenset[str]:
        return frozenset({f"127.0.0.1:{self.port}", f"localhost:{self.port}"})

    @property
    def allowed_origins(self) -> frozenset[str]:
        return frozenset({f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"})


def refusal_reason(config: GuardConfig, method: str, path: str, headers: Headers) -> str | None:
    """Why a request must be refused, or None when it may pass."""
    if headers.get("host", "") not in config.allowed_hosts:
        return "host"
    origin = headers.get("origin")
    if origin is not None and origin not in config.allowed_origins:
        return "origin"
    fetch_site = headers.get("sec-fetch-site")
    if fetch_site is not None and fetch_site not in _TRUSTED_FETCH_SITES:
        return "fetch-site"
    if method not in _SAFE_METHODS and origin is None:
        return "origin"
    if path.startswith("/api/"):
        supplied = headers.get(TOKEN_HEADER, "").encode("latin-1")
        if not hmac.compare_digest(supplied, config.token.encode("ascii")):
            return "token"
    return None


class LocalOnlyGuard:
    def __init__(self, app: ASGIApp, config: GuardConfig) -> None:
        self.app = app
        self.config = config

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            await receive()
            await send({"type": "websocket.close", "code": 1008})
            return
        headers = Headers(scope=scope)
        reason = refusal_reason(self.config, scope["method"], scope["path"], headers)
        if reason is not None:
            response = PlainTextResponse(f"Refused: {reason}", status_code=403)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
```

- [ ] **Step 4: Run the guard tests.**

Run: `uv run pytest tests/unit/test_security.py -v`
Expected: PASS. If `TestClient` reports a missing HTTP client package, Starlette 1.7 names the one it needs in the error (`httpx` or `httpx2`): add that to the dev group, note it in `docs/decisions/NNNN-test-client.md`, and rerun.

- [ ] **Step 5: Write the failing app tests.** `tests/unit/test_server.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from mihenk import __version__
from mihenk.api.routes.smoke import SmokeSignal
from mihenk.api.security import TOKEN_HEADER, GuardConfig
from mihenk.api.server import create_app

PORT = 51235
TOKEN = "server-test-token-0123456789"
BASE = f"http://127.0.0.1:{PORT}"
GOOD = {TOKEN_HEADER: TOKEN, "origin": BASE}


def client(web_dist: Path | None = None, smoke: SmokeSignal | None = None) -> TestClient:
    app = create_app(GuardConfig(port=PORT, token=TOKEN), web_dist=web_dist, smoke_signal=smoke)
    return TestClient(app, base_url=BASE)


def test_health() -> None:
    response = client().get("/api/health", headers=GOOD)
    assert response.json() == {"status": "ok", "version": __version__}


def test_docs_and_openapi_routes_are_off() -> None:
    for path in ("/docs", "/redoc", "/openapi.json", "/api/openapi.json"):
        assert client().get(path, headers=GOOD).status_code == 404


def test_unbuilt_screens_show_a_hint() -> None:
    response = client(web_dist=None).get("/")
    assert response.status_code == 200
    assert "npm run build" in response.text


def test_built_screens_are_served(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<!doctype html><title>mihenk</title>", encoding="utf-8")
    response = client(web_dist=tmp_path).get("/")
    assert "<title>mihenk</title>" in response.text


def test_smoke_route_is_404_outside_smoke_mode() -> None:
    assert client().post("/api/smoke/ok", headers=GOOD).status_code == 404


def test_smoke_route_sets_the_signal() -> None:
    signal = SmokeSignal()
    response = client(smoke=signal).post("/api/smoke/ok", headers=GOOD)
    assert response.json() == {"received": True}
    assert signal.event.is_set()


def test_openapi_schema_is_still_buildable_in_process() -> None:
    app = create_app(GuardConfig(port=PORT, token=TOKEN), web_dist=None)
    schema = app.openapi()
    assert "/api/health" in schema["paths"]
```

- [ ] **Step 6: Run to see them fail.** `uv run pytest tests/unit/test_server.py -v` → FAIL (`ModuleNotFoundError`).

- [ ] **Step 7: Write the routes and the app.** `src/mihenk/api/routes/health.py`:

```python
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from mihenk import __version__

router = APIRouter()


class Health(BaseModel):
    status: Literal["ok"]
    version: str


@router.get("/health", response_model=Health)
def health() -> Health:
    return Health(status="ok", version=__version__)
```

`src/mihenk/api/routes/smoke.py`:

```python
"""The release check: in --smoke mode the screens call this once they reach the server."""

import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class SmokeSignal:
    def __init__(self) -> None:
        self.event = threading.Event()


class SmokeAck(BaseModel):
    received: bool


def make_router(signal: SmokeSignal | None) -> APIRouter:
    router = APIRouter()

    @router.post("/smoke/ok", response_model=SmokeAck)
    def smoke_ok() -> SmokeAck:
        if signal is None:
            raise HTTPException(status_code=404, detail="not in smoke mode")
        signal.event.set()
        return SmokeAck(received=True)

    return router
```

`src/mihenk/api/server.py`:

```python
"""The FastAPI application (design §5, §14)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from mihenk import __version__
from mihenk.api.routes import health, smoke
from mihenk.api.routes.smoke import SmokeSignal
from mihenk.api.security import GuardConfig, LocalOnlyGuard

_NOT_BUILT = (
    "<!doctype html><title>mihenk</title>"
    "<p>The screens are not built yet. Run <code>npm run build</code> in <code>web/</code>.</p>"
)


def create_app(
    config: GuardConfig, web_dist: Path | None, smoke_signal: SmokeSignal | None = None
) -> FastAPI:
    # docs_url, redoc_url and openapi_url are off: the docs pages load scripts from a CDN (§14).
    app = FastAPI(
        title="mihenk", version=__version__, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.include_router(health.router, prefix="/api")
    app.include_router(smoke.make_router(smoke_signal), prefix="/api")
    if web_dist is not None and (web_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="screens")
    else:

        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        def not_built() -> str:
            return _NOT_BUILT

    app.add_middleware(LocalOnlyGuard, config=config)
    return app
```

Create empty `src/mihenk/api/__init__.py` and `src/mihenk/api/routes/__init__.py`.

- [ ] **Step 8: Run all checks.** `uv run pytest -v && uv run mypy && uv run ruff check .` → all pass.

- [ ] **Step 9: Commit.** `git add -A && git commit -m "Local server with the Host, Origin and token guard"`

### Task 0.4: The screens skeleton, its build hook and the API types

**Files:**
- Create: `web/package.json`, `web/package-lock.json`, `web/tsconfig.json`, `web/vite.config.ts`, `web/eslint.config.js`, `web/index.html`, `web/src/main.tsx`, `web/src/App.tsx`, `web/src/api/client.ts`, `web/src/api/schema.ts` (generated), `web/openapi.json` (generated), `web/src/App.test.tsx`, `web/src/api/client.test.ts`, `hatch_build.py`, `tools/dump_openapi.py`
- Modify: `pyproject.toml` (add the wheel build hook)

**Interfaces:**
- Consumes: `create_app`, `GuardConfig`, `Health`, `SmokeAck` (Task 0.3).
- Produces: the built screens in `src/mihenk/web_dist/`; `readLaunchParams(location, storage, history) -> { token: string | null; smoke: boolean }`; `apiFetch(path, init)` that adds the `X-Mihenk-Token` header; `getHealth(signal)`, `sendSmokeOk(signal)`.

- [ ] **Step 1: Create the app and install packages.** In `web/`, write `package.json`:

```json
{
  "name": "mihenk-web",
  "private": true,
  "license": "PolyForm-Noncommercial-1.0.0",
  "type": "module",
  "scripts": {
    "build": "tsc -b && vite build",
    "watch": "vite build --watch",
    "typecheck": "tsc -b",
    "lint": "eslint .",
    "test": "vitest run",
    "gen:api": "openapi-typescript openapi.json -o src/api/schema.ts"
  }
}
```

Then install (npm records the exact versions in the lockfile):

```bash
npm install react@^19.3.0 react-dom@^19.3.0
npm install -D vite@^8.3.4 @vitejs/plugin-react typescript openapi-typescript@^7.13.0 vitest jsdom @testing-library/react @testing-library/jest-dom @types/react @types/react-dom eslint @eslint/js typescript-eslint eslint-plugin-react-hooks
```

`tsconfig.json`: `"strict": true`, `"noUncheckedIndexedAccess": true`, `"exactOptionalPropertyTypes": true`, `"noImplicitReturns": true`, `"noFallthroughCasesInSwitch": true`, `"skipLibCheck": true`, `"jsx": "react-jsx"`, `"module": "ESNext"`, `"moduleResolution": "Bundler"`, `"target": "ES2022"`, `"noEmit": true`, `"types": ["vitest/globals", "@testing-library/jest-dom"]`, including `src` and `vite.config.ts`.

If `npm run typecheck` still fails only because Node's types are missing, add `@types/node@^24` as a dev dependency (type definitions only, MIT, never shipped) and record why in `docs/decisions/NNNN-node-types.md`; no other unnamed dependency is added.

`eslint.config.js`: `@eslint/js` recommended, `typescript-eslint` strict type-checked, and `eslint-plugin-react-hooks` recommended rules; ignore `src/api/schema.ts`.

`vite.config.ts`:

```ts
/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    // Inside the Python package, not "dist", which collides with PyInstaller's folder (§17).
    // Relative to web/, so no Node types are needed to type-check this file.
    outDir: "../src/mihenk/web_dist",
    emptyOutDir: true,
  },
  test: { environment: "jsdom", globals: true },
});
```

`index.html`: a plain HTML5 page with `<html lang="en">`, `<title>mihenk</title>`, `<div id="root"></div>` and `<script type="module" src="/src/main.tsx"></script>`. It must load nothing from another origin.

- [ ] **Step 2: Generate the API types.** `tools/dump_openapi.py`:

```python
"""Writes web/openapi.json from the FastAPI app, for openapi-typescript (design §5)."""

import json
from pathlib import Path

from mihenk.api.security import GuardConfig
from mihenk.api.server import create_app


def main() -> None:
    app = create_app(GuardConfig(port=1, token="x" * 32), web_dist=None)
    out = Path(__file__).resolve().parent.parent / "web" / "openapi.json"
    out.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
```

Run: `uv run python tools/dump_openapi.py && (cd web && npm run gen:api)`
Expected: `web/openapi.json` and `web/src/api/schema.ts` exist, and `schema.ts` contains `Health`.

- [ ] **Step 3: Write the failing screen tests.** `web/src/api/client.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { readLaunchParams } from "./client";

function fakeLocation(hash: string): Location {
  return { hash, pathname: "/", search: "" } as Location;
}

describe("readLaunchParams", () => {
  it("takes the token from the fragment, stores it and clears the fragment", () => {
    const calls: string[] = [];
    const history = { replaceState: (_d: unknown, _t: string, url: string) => calls.push(url) } as unknown as History;
    const result = readLaunchParams(fakeLocation("#token=abc&smoke=1"), sessionStorage, history);
    expect(result).toEqual({ token: "abc", smoke: true });
    expect(sessionStorage.getItem("mihenk.token")).toBe("abc");
    expect(calls).toEqual(["/"]);
  });

  it("falls back to the stored token after a reload", () => {
    sessionStorage.setItem("mihenk.token", "stored");
    const history = { replaceState: () => undefined } as unknown as History;
    expect(readLaunchParams(fakeLocation(""), sessionStorage, history)).toEqual({ token: "stored", smoke: false });
  });
});
```

`web/src/App.test.tsx`: render `<App smoke={false} />` with `globalThis.fetch` mocked to resolve `{ status: "ok", version: "0.0.1" }` and expect the text `Connected to mihenk 0.0.1`; with fetch rejecting, expect a `role="alert"` element containing `Cannot reach the mihenk server`; with `smoke={true}`, expect a second fetch call to `/api/smoke/ok` with method `POST`. Every fetch call must carry the `X-Mihenk-Token` header.

Run: `cd web && npm test` → FAIL (modules missing).

- [ ] **Step 4: Write the client and the app.** `web/src/api/client.ts`:

```ts
import type { components } from "./schema";

export type Health = components["schemas"]["Health"];

const TOKEN_KEY = "mihenk.token";
let token: string | null = null;

export function readLaunchParams(
  location: Location,
  storage: Storage,
  history: History,
): { token: string | null; smoke: boolean } {
  const params = new URLSearchParams(location.hash.replace(/^#/, ""));
  const fromHash = params.get("token");
  if (fromHash !== null) {
    storage.setItem(TOKEN_KEY, fromHash);
    history.replaceState(null, "", location.pathname + location.search);
  }
  return { token: fromHash ?? storage.getItem(TOKEN_KEY), smoke: params.get("smoke") === "1" };
}

export function setToken(value: string): void {
  token = value;
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  if (token === null) throw new Error("No launch token. Open mihenk from its app window.");
  const headers = new Headers(init.headers);
  headers.set("X-Mihenk-Token", token);
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) throw new Error(`The mihenk server answered ${String(response.status)}`);
  return response;
}

function isHealth(value: unknown): value is Health {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return v.status === "ok" && typeof v.version === "string";
}

export async function getHealth(signal: AbortSignal): Promise<Health> {
  const body: unknown = await (await apiFetch("/api/health", { signal })).json();
  if (!isHealth(body)) throw new Error("The mihenk server sent an unexpected answer");
  return body;
}

export async function sendSmokeOk(signal: AbortSignal): Promise<void> {
  await apiFetch("/api/smoke/ok", { method: "POST", signal });
}
```

`web/src/App.tsx`: a `Status` discriminated union (`loading`, `ok` with `health`, `error` with `message`); one effect that calls `getHealth` with an `AbortController`, then `sendSmokeOk` when `smoke` is true, and aborts on unmount; renders `<main>` with `<h1>mihenk</h1>` and either `Checking the connection…`, `Connected to mihenk {version}`, or `<p role="alert">Cannot reach the mihenk server: {message}</p>`.

`web/src/main.tsx`: calls `readLaunchParams(window.location, window.sessionStorage, window.history)`; if the token is null, renders the alert `Open mihenk from its app window.`; otherwise calls `setToken` and renders `<App smoke={smoke} />` in `StrictMode`.

- [ ] **Step 5: Run the screen checks.** `cd web && npm run lint && npm run typecheck && npm test && npm run build` → all pass; `src/mihenk/web_dist/index.html` exists.

- [ ] **Step 6: The wheel build hook.** `hatch_build.py`:

```python
"""Builds the React screens into the package before a wheel is made (design §17)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class WebBuildHook(BuildHookInterface):  # type: ignore[misc]
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if version == "editable" or os.environ.get("MIHENK_SKIP_WEB_BUILD") == "1":
            return
        npm = shutil.which("npm")
        if npm is None:
            raise RuntimeError("npm is needed to build the mihenk screens; install Node.js 24")
        web = Path(self.root) / "web"
        subprocess.run([npm, "ci"], cwd=web, check=True)
        subprocess.run([npm, "run", "build"], cwd=web, check=True)
        index = Path(self.root) / "src" / "mihenk" / "web_dist" / "index.html"
        if not index.is_file():
            raise RuntimeError("the screens build produced no index.html")
```

Add to `pyproject.toml`:

```toml
[tool.hatch.build.targets.wheel.hooks.custom]
path = "hatch_build.py"
```

Run: `uv build --wheel` then list the wheel's contents (`uv run python -m zipfile -l dist/mihenk-0.0.1-py3-none-any.whl`).
Expected: the listing contains `mihenk/web_dist/index.html`.

- [ ] **Step 7: Commit.** `git add -A && git commit -m "Screens skeleton, wheel build hook and generated API types"`

### Task 0.5: The launcher: data folder, server thread, window and smoke mode

**Files:**
- Create: `src/mihenk/app/__init__.py`, `src/mihenk/app/paths.py`, `src/mihenk/app/launcher.py`, `src/mihenk/__main__.py`
- Test: `tests/unit/test_launcher.py`, `tests/integration/test_server_thread.py`

**Interfaces:**
- Consumes: `create_app`, `GuardConfig`, `SmokeSignal` (Task 0.3); the built screens (Task 0.4).
- Produces: `default_data_dir() -> Path`, `logs_dir(data_dir: Path) -> Path`; `new_token() -> str`, `bind_loopback() -> socket.socket`, `launch_url(port: int, token: str, *, smoke: bool = False) -> str`, `bundled_web_dist() -> Path`, `ServerThread(app, sock)` with `.start(timeout_s)`, `.stop(timeout_s)`, `.running`; `ServerStartError`; `main(argv: Sequence[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing unit tests.** `tests/unit/test_launcher.py`:

```python
import socket
from pathlib import Path

from mihenk.app.launcher import bind_loopback, launch_url, new_token
from mihenk.app.paths import logs_dir


def test_bind_loopback_gives_a_free_local_port() -> None:
    sock = bind_loopback()
    try:
        host, port = sock.getsockname()[:2]
        assert host == "127.0.0.1"
        assert port > 0
        assert sock.family == socket.AF_INET
    finally:
        sock.close()


def test_tokens_are_long_unique_and_url_safe() -> None:
    tokens = {new_token() for _ in range(20)}
    assert len(tokens) == 20
    assert all(len(t) >= 40 and t.isascii() for t in tokens)
    assert all(
        set(t) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
        for t in tokens
    )


def test_launch_url_keeps_the_token_in_the_fragment() -> None:
    assert launch_url(5000, "abc") == "http://127.0.0.1:5000/#token=abc"
    assert launch_url(5000, "abc", smoke=True) == "http://127.0.0.1:5000/#token=abc&smoke=1"


def test_data_dir_override_with_spaces_and_turkish_letters(tmp_path: Path) -> None:
    data_dir = tmp_path / "Ayşe Yılmaz" / "mihenk data"
    logs = logs_dir(data_dir)
    assert logs.is_dir()
    (logs / "probe.txt").write_text("şğıİ", encoding="utf-8")
    assert (logs / "probe.txt").read_text(encoding="utf-8") == "şğıİ"
```

`tests/integration/test_server_thread.py`:

```python
import httpx

from mihenk.api.security import TOKEN_HEADER, GuardConfig
from mihenk.api.server import create_app
from mihenk.app.launcher import ServerThread, bind_loopback, new_token


def test_server_thread_serves_and_stops() -> None:
    sock = bind_loopback()
    port = sock.getsockname()[1]
    token = new_token()
    server = ServerThread(create_app(GuardConfig(port=port, token=token), web_dist=None), sock)
    server.start()
    try:
        response = httpx.get(f"http://127.0.0.1:{port}/api/health", headers={TOKEN_HEADER: token})
        assert response.status_code == 200
    finally:
        server.stop()
    assert not server.running
```

Run: `uv run pytest tests/unit/test_launcher.py tests/integration/test_server_thread.py -v` → FAIL (`ModuleNotFoundError`).

- [ ] **Step 2: Write the paths module.** `src/mihenk/app/paths.py`:

```python
"""Where mihenk keeps its data on the user's machine."""

import os
from pathlib import Path

import platformdirs

APP_NAME = "mihenk"


def default_data_dir() -> Path:
    # appauthor=False avoids ...\mihenk\mihenk on Windows. realpath() gives the real folder
    # when Microsoft Store Python redirects AppData (§22).
    raw = platformdirs.user_data_dir(APP_NAME, appauthor=False, ensure_exists=True)
    return Path(os.path.realpath(raw))


def logs_dir(data_dir: Path) -> Path:
    path = data_dir / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path
```

- [ ] **Step 3: Write the launcher.** `src/mihenk/app/launcher.py`:

```python
"""Starts mihenk: data folder, local server, window (design §5).

The window owns the main thread, as pywebview requires. The server runs under uvicorn in a
background thread and is told to exit when the window closes.
"""

from __future__ import annotations

import argparse
import logging
import secrets
import socket
import threading
import time
import webbrowser
from collections.abc import Sequence
from importlib import resources
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from mihenk.api.routes.smoke import SmokeSignal
from mihenk.api.security import GuardConfig
from mihenk.api.server import create_app
from mihenk.app.paths import default_data_dir, logs_dir

log = logging.getLogger(__name__)


class ServerStartError(RuntimeError):
    pass


def new_token() -> str:
    return secrets.token_urlsafe(32)


def bind_loopback() -> socket.socket:
    """A socket on 127.0.0.1 with a free port, handed to uvicorn so no other process can take it."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    return sock


def launch_url(port: int, token: str, *, smoke: bool = False) -> str:
    fragment = f"token={token}" + ("&smoke=1" if smoke else "")
    return f"http://127.0.0.1:{port}/#{fragment}"


def bundled_web_dist() -> Path:
    return Path(str(resources.files("mihenk") / "web_dist"))


class ServerThread:
    def __init__(self, app: FastAPI, sock: socket.socket) -> None:
        # proxy_headers=False: uvicorn otherwise trusts X-Forwarded-* from 127.0.0.1, and every
        # caller of this server is on 127.0.0.1, so any local program could set them.
        # log_config=None: uvicorn's default config needs a console (the windowed build has
        # none) and stops its loggers propagating, so server errors would miss mihenk.log.
        config = uvicorn.Config(
            app, log_level="warning", access_log=False, proxy_headers=False, log_config=None
        )
        self._server = uvicorn.Server(config)
        self._sock = sock
        self._thread = threading.Thread(target=self._run, name="mihenk-server", daemon=True)

    def _run(self) -> None:
        self._server.run(sockets=[self._sock])

    def start(self, timeout_s: float = 10.0) -> None:
        self._thread.start()
        deadline = time.monotonic() + timeout_s
        while not self._server.started:
            if not self._thread.is_alive():
                raise ServerStartError("the local server stopped while starting")
            if time.monotonic() > deadline:
                raise ServerStartError("the local server did not start in time")
            time.sleep(0.02)

    def stop(self, timeout_s: float = 10.0) -> None:
        self._server.should_exit = True
        self._thread.join(timeout_s)
        self._sock.close()

    @property
    def running(self) -> bool:
        return self._thread.is_alive()


def run_window(url: str) -> None:
    import webview

    webview.create_window("mihenk", url, width=1280, height=800, min_size=(960, 640))
    webview.start()


def run_window_smoke(url: str, signal: SmokeSignal, timeout_s: float) -> bool:
    """Opens the real window; passes when the screens reach the server within timeout_s."""
    import webview

    window = webview.create_window("mihenk (release check)", url)

    def watch() -> None:
        signal.event.wait(timeout_s)
        window.destroy()

    webview.start(watch)
    return signal.event.is_set()


def _wait_for_interrupt() -> None:
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        return


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mihenk", description="Track competitors' pricing and packaging."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--browser", action="store_true", help="open the screens in your web browser")
    mode.add_argument("--smoke", action="store_true", help="release check: open, connect, exit")
    parser.add_argument("--smoke-timeout", type=float, default=60.0, help=argparse.SUPPRESS)
    parser.add_argument("--data-dir", type=Path, default=None, help="use this data folder")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse(argv)
    data_dir: Path = args.data_dir or default_data_dir()
    logging.basicConfig(
        filename=logs_dir(data_dir) / "mihenk.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        encoding="utf-8",
    )
    sock = bind_loopback()
    port = int(sock.getsockname()[1])
    token = new_token()
    smoke = SmokeSignal() if args.smoke else None
    app = create_app(GuardConfig(port=port, token=token), bundled_web_dist(), smoke)
    server = ServerThread(app, sock)
    server.start()
    log.info("mihenk started on 127.0.0.1:%d", port)
    url = launch_url(port, token, smoke=args.smoke)
    try:
        if smoke is not None:
            return 0 if run_window_smoke(url, smoke, args.smoke_timeout) else 1
        if args.browser:
            webbrowser.open(url)
            _wait_for_interrupt()
            return 0
        run_window(url)
        return 0
    finally:
        server.stop()
```

The token is never logged. `src/mihenk/__main__.py`:

```python
from mihenk.app.launcher import main

raise SystemExit(main())
```

Create empty `src/mihenk/app/__init__.py`.

- [ ] **Step 4: Run the tests and checks.** `uv run pytest -v && uv run mypy && uv run ruff check .` → all pass.

- [ ] **Step 5: Try it by hand.** `cd web && npm run build && cd .. && uv run mihenk` opens a window titled mihenk showing `Connected to mihenk 0.0.1`; closing the window ends the process. `uv run mihenk --smoke; echo $?` prints `0` within a few seconds (in PowerShell, `$LASTEXITCODE`). Record what happened in the task report; a failure here is a stage-0 finding, not something to work around. An agent runs only the `--smoke` check; opening the window and closing it by hand is Aydin's check, listed in the stage-0 report.

- [ ] **Step 6: Commit.** `git add -A && git commit -m "Launcher: server thread, window, smoke mode"`

### Task 0.6: Driving the installed browser once

**Files:**
- Create: `src/mihenk/capture/__init__.py`, `src/mihenk/capture/browser.py`, `tests/__init__.py`, `tests/helpers/__init__.py`, `tests/helpers/site.py`, `tests/conftest.py`, `tests/fixtures/pages/smoke/page.html`
- Test: `tests/unit/test_network_guard.py`, `tests/integration/test_browser.py`, `tests/integration/test_browser_missing.py`

**Interfaces:**
- Produces: `CHANNEL_ORDER = ("chrome", "msedge")`, `BrowserUnavailable(tried: Sequence[str])` with `.tried`, `LaunchedBrowser(channel: str, browser: playwright.sync_api.Browser)`, `launch_browser(pw: Playwright, *, headless: bool = True, allow_downloaded: bool = False) -> LaunchedBrowser`; test helpers `LocalSite` (`add`, `add_file`, `redirect`, `url`, `base_url`, `hits`) and the pytest fixtures `site`, `pw` (the one Playwright session of the test run) and `browser` (a `LaunchedBrowser`; tests pass `browser.browser` where a Playwright `Browser` is needed).
- Rule for every later test: Playwright's sync API allows one session per thread, so no test calls `sync_playwright()` itself. A test that needs Playwright takes `pw` or `browser`; code under test that starts its own Playwright session (the CLI) is run in a subprocess.

- [ ] **Step 1: The test web server.** `tests/helpers/site.py`:

```python
"""A small website on 127.0.0.1 for tests. The network guard allows only loopback."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


@dataclass
class Route:
    status: int = 200
    body: bytes = b""
    content_type: str = "text/html; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)
    delay_s: float = 0.0


class LocalSite:
    def __init__(self) -> None:
        self.routes: dict[str, Route] = {}
        self.hits: list[str] = []
        self._server: ThreadingHTTPServer | None = None

    def add(
        self,
        path: str,
        body: str | bytes = b"",
        *,
        status: int = 200,
        content_type: str = "text/html; charset=utf-8",
        headers: dict[str, str] | None = None,
        delay_s: float = 0.0,
    ) -> None:
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.routes[path] = Route(status, data, content_type, dict(headers or {}), delay_s)

    def add_file(
        self, path: str, file: Path, content_type: str = "text/html; charset=utf-8"
    ) -> None:
        self.add(path, file.read_bytes(), content_type=content_type)

    def redirect(self, path: str, to: str, status: int = 302) -> None:
        self.add(path, b"", status=status, headers={"Location": to})

    @property
    def base_url(self) -> str:
        assert self._server is not None
        port = self._server.server_address[1]
        return f"http://127.0.0.1:{port}"

    def url(self, path: str) -> str:
        return self.base_url + path

    def __enter__(self) -> LocalSite:
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self._serve(head=False)

            def do_HEAD(self) -> None:
                self._serve(head=True)

            def _serve(self, *, head: bool) -> None:
                path = self.path.split("?", 1)[0]
                site.hits.append(path)
                route = site.routes.get(path)
                if route is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if route.delay_s:
                    time.sleep(route.delay_s)
                self.send_response(route.status)
                self.send_header("Content-Type", route.content_type)
                self.send_header("Content-Length", str(len(route.body)))
                for name, value in route.headers.items():
                    self.send_header(name, value)
                self.end_headers()
                if not head:
                    self.wfile.write(route.body)

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc: object) -> None:
        assert self._server is not None
        self._server.shutdown()
        self._server.server_close()
```

- [ ] **Step 2: The network guard and shared fixtures.** `tests/conftest.py`:

```python
"""Shared fixtures. Every test runs behind a guard that allows loopback connections only."""

from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Iterator
from typing import Any

import pytest

from tests.helpers.site import LocalSite

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


class NetworkBlocked(RuntimeError):
    pass


def _check(sock: socket.socket, address: Any) -> None:
    if getattr(socket, "AF_UNIX", None) is not None and sock.family == socket.AF_UNIX:
        return
    host = address[0] if isinstance(address, tuple) else address
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise NetworkBlocked(f"a test tried to reach {host!r}") from None
    if not ip.is_loopback:
        raise NetworkBlocked(f"a test tried to reach {host}")


def _guarded_connect(self: socket.socket, address: Any) -> None:
    _check(self, address)
    _real_connect(self, address)


def _guarded_connect_ex(self: socket.socket, address: Any) -> int:
    _check(self, address)
    return _real_connect_ex(self, address)


@pytest.fixture(autouse=True)
def _loopback_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _guarded_connect_ex)


@pytest.fixture
def site() -> Iterator[LocalSite]:
    with LocalSite() as running:
        yield running


@pytest.fixture(scope="session")
def pw() -> Iterator[Any]:
    """The one Playwright session of the test run: the sync API allows one per thread."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as session:
        yield session


@pytest.fixture(scope="session")
def browser(pw: Any) -> Iterator[Any]:
    from mihenk.capture.browser import BrowserUnavailable, launch_browser

    try:
        launched = launch_browser(pw)
    except BrowserUnavailable as exc:
        if os.environ.get("MIHENK_REQUIRE_BROWSER") == "1":
            pytest.fail(str(exc))
        pytest.skip(str(exc))
    yield launched
    launched.browser.close()
```

Create an empty `tests/__init__.py` in this step, so `tests.helpers` imports from the conftest.

The guard covers Python sockets only. Chrome is a separate process; browser tests reach only `LocalSite`, by design.

Amended during execution (Task 0.6 review): Windows' default asyncio loop connects through `asyncio.windows_events.IocpProactor.connect` (ConnectEx), which never calls `socket.connect`. On Windows the fixture also patches that method with the same `_check`, and `test_network_guard.py` adds `test_asyncio_connections_are_blocked` (an `asyncio.open_connection` to the documentation address 192.0.2.1, run on its own thread because the session's Playwright keeps a loop running on the main one).

Add a test that the guard works, `tests/unit/test_network_guard.py`:

```python
import socket
import urllib.request

import pytest

from tests.helpers.site import LocalSite


def test_reaching_the_internet_is_blocked() -> None:
    with socket.socket() as sock, pytest.raises(RuntimeError, match="tried to reach"):
        sock.connect(("93.184.216.34", 80))


def test_loopback_is_allowed(site: LocalSite) -> None:
    site.add("/", "ok")
    with urllib.request.urlopen(site.url("/")) as response:  # noqa: S310 (a loopback test URL)
        assert response.read() == b"ok"
```

- [ ] **Step 3: Write the failing browser test.** `tests/fixtures/pages/smoke/page.html`:

```html
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>mihenk smoke page</title></head>
<body><p>Hello from the test site.</p></body></html>
```

`tests/integration/test_browser.py`:

```python
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "pages"


@pytest.mark.browser
def test_drives_the_installed_browser_once(site, browser) -> None:  # type: ignore[no-untyped-def]
    site.add_file("/smoke", FIXTURES / "smoke" / "page.html")
    context = browser.browser.new_context(accept_downloads=False)
    try:
        page = context.new_page()
        page.goto(site.url("/smoke"))
        assert page.title() == "mihenk smoke page"
    finally:
        context.close()
    assert browser.channel in ("chrome", "msedge")
```

Run: `uv run pytest tests/integration/test_browser.py -v` → FAIL (`ModuleNotFoundError: mihenk.capture.browser`).

- [ ] **Step 4: Write the browser module.** `src/mihenk/capture/browser.py`:

```python
"""Finding a browser to drive (design §17): installed Chrome, then installed Edge.

Playwright's own Chromium is used only after the user agreed to download it (Task 1.10).
Playwright is not thread-safe: everything here runs on the one capture thread.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from playwright.sync_api import Browser, Playwright
from playwright.sync_api import Error as PlaywrightError

CHANNEL_ORDER: tuple[str, ...] = ("chrome", "msedge")
# Playwright reports a missing branded browser with this phrase. It is not documented API
# (checked against Playwright 1.63's source, §22), so a test pins it.
_NOT_FOUND = "is not found at"


class BrowserUnavailable(Exception):
    def __init__(self, tried: Sequence[str]) -> None:
        super().__init__("No usable browser found. Tried: " + ", ".join(tried))
        self.tried = tuple(tried)


@dataclass(frozen=True)
class LaunchedBrowser:
    channel: str
    browser: Browser


def launch_browser(
    pw: Playwright, *, headless: bool = True, allow_downloaded: bool = False
) -> LaunchedBrowser:
    tried: list[str] = []
    channels = CHANNEL_ORDER + (("chromium",) if allow_downloaded else ())
    for channel in channels:
        try:
            return LaunchedBrowser(channel, pw.chromium.launch(channel=channel, headless=headless))
        except PlaywrightError as exc:
            if _NOT_FOUND not in str(exc) and "Executable doesn't exist" not in str(exc):
                raise
            tried.append(channel)
    raise BrowserUnavailable(tried)
```

Create empty `src/mihenk/capture/__init__.py` and `tests/helpers/__init__.py`.

- [ ] **Step 5: Pin the "not found" message.** Add `tests/integration/test_browser_missing.py` that takes the session `pw` fixture (never its own `sync_playwright()`), launches `channel="chrome-canary"` (not installed on CI runners), catches `PlaywrightError`, and asserts `"is not found at" in str(exc)` or `"Executable doesn't exist" in str(exc)`. If Canary happens to be installed, the test skips. This test fails loudly the day Playwright changes the wording.

- [ ] **Step 6: Run.** `uv run pytest -v` → all pass (the browser test skips only if neither Chrome nor Edge is installed and `MIHENK_REQUIRE_BROWSER` is unset).

- [ ] **Step 7: Commit.** `git add -A && git commit -m "Drive the installed Chrome or Edge; loopback-only test guard"`

### Task 0.7: Repository checks: licences, notices, price arithmetic

**Files:**
- Create: `tools/check_licenses.py`, `tools/license_overrides.toml`, `tools/gen_notices.py`, `tools/check_price_arithmetic.py`
- Test: `tests/unit/test_check_licenses.py`, `tests/unit/test_check_price_arithmetic.py`

**Interfaces:**
- Produces: `spdx_allowed(expression: str, allowed: frozenset[str]) -> bool`; `python_violations(path: Path, source: str) -> list[Violation]`, `typescript_violations(path: Path, source: str) -> list[Violation]`, `scan(root: Path) -> list[Violation]`, `PRICE_FIELDS`, `EXEMPT`; `THIRD_PARTY_NOTICES.txt` produced by `gen_notices.py`.

- [ ] **Step 1: Write the failing licence tests.** `tests/unit/test_check_licenses.py`:

```python
import pytest

from tools.check_licenses import ALLOWED, spdx_allowed


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
```

Add an empty `tools/__init__.py` so tests import `tools.*`.

- [ ] **Step 2: Write the licence checker.** `tools/check_licenses.py`:

```python
"""Fails when a runtime dependency's licence is not on the allow-list (design §18).

Python: the runtime closure from `uv export --no-dev`, read from installed metadata
(License-Expression first, then classifiers, then tools/license_overrides.toml).
Screens: production npm packages from `npm ls --omit=dev --all --json`.
GPL and AGPL always fail; LGPL fails unless listed in APPROVED_LGPL.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tomllib
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED = frozenset(
    {
        "MIT",
        "MIT-0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "Apache-2.0",
        "ISC",
        "0BSD",
        "PSF-2.0",
        "Python-2.0",
        "MPL-2.0",
        "Unlicense",
        "CC0-1.0",
        "BlueOak-1.0.0",
        "Zlib",
    }
)
APPROVED_LGPL: frozenset[str] = frozenset()  # package names Aydin approved, with a decision record
_CLASSIFIERS = {
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: BSD License": "BSD-3-Clause",
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: ISC License (ISCL)": "ISC",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
}


def spdx_allowed(expression: str, allowed: frozenset[str]) -> bool:
    tokens = re.findall(r"\(|\)|[A-Za-z0-9.+:-]+", expression)
    pos = 0

    def atom() -> bool:
        nonlocal pos
        if pos >= len(tokens):
            raise ValueError(f"incomplete licence expression: {expression!r}")
        token = tokens[pos]
        pos += 1
        if token == "(":
            value = either()
            if pos >= len(tokens) or tokens[pos] != ")":
                raise ValueError(f"unbalanced licence expression: {expression!r}")
            pos += 1
            return value
        if pos < len(tokens) and tokens[pos].upper() == "WITH":
            pos += 2  # an exception never makes a licence acceptable by itself
        return token in allowed

    def both() -> bool:
        nonlocal pos
        value = atom()
        while pos < len(tokens) and tokens[pos].upper() == "AND":
            pos += 1
            right = atom()
            value = value and right
        return value

    def either() -> bool:
        nonlocal pos
        value = both()
        while pos < len(tokens) and tokens[pos].upper() == "OR":
            pos += 1
            right = both()
            value = value or right
        return value

    result = either()
    if pos != len(tokens):
        raise ValueError(f"unexpected text in licence expression: {expression!r}")
    return result


def _python_runtime_names() -> list[str]:
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv is needed for the licence check")
    exported = subprocess.run(
        [
            uv,
            "export",
            "--no-dev",
            "--no-emit-project",
            "--no-hashes",
            "--format",
            "requirements-txt",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    names = []
    for line in exported.splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "-")):
            names.append(re.split(r"[=<>!~;\s\[]", line, maxsplit=1)[0])
    return names


def _python_expression(name: str, overrides: dict[str, str]) -> str | None:
    if name.lower() in overrides:
        return overrides[name.lower()]
    meta = metadata.metadata(name)
    if meta.get("License-Expression"):
        return str(meta["License-Expression"])
    for classifier in meta.get_all("Classifier") or []:
        if classifier in _CLASSIFIERS:
            return _CLASSIFIERS[classifier]
    return None


def main() -> int:
    overrides_file = ROOT / "tools" / "license_overrides.toml"
    overrides = {
        k.lower(): v["spdx"] for k, v in tomllib.loads(overrides_file.read_text("utf-8")).items()
    }
    problems: list[str] = []
    for name in _python_runtime_names():
        try:
            expression = _python_expression(name, overrides)
        except metadata.PackageNotFoundError:
            print(f"skip {name}: not installed on this platform (checked on the other CI system)")
            continue
        if expression is None:
            problems.append(
                f"python {name}: licence unknown; add it to tools/license_overrides.toml"
            )
        elif name.lower() in APPROVED_LGPL:
            continue
        elif not spdx_allowed(expression, ALLOWED):
            problems.append(f"python {name}: {expression}")
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("npm is needed for the licence check")
    tree = json.loads(
        subprocess.run(
            [npm, "ls", "--omit=dev", "--all", "--json"],
            cwd=ROOT / "web",
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    stack = list((tree.get("dependencies") or {}).items())
    while stack:
        name, node = stack.pop()
        package_json = ROOT / "web" / "node_modules" / name / "package.json"
        expression = json.loads(package_json.read_text("utf-8")).get("license")
        if not isinstance(expression, str) or not spdx_allowed(expression, ALLOWED):
            problems.append(f"npm {name}: {expression!r}")
        stack.extend((node.get("dependencies") or {}).items())
    for problem in problems:
        print("LICENCE PROBLEM", problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
```

`tools/license_overrides.toml` starts with a comment explaining the format and no entries:

```toml
# One table per package whose metadata does not state an SPDX licence.
# [package-name]
# spdx = "BSD-3-Clause"
# source = "https://... (where the licence was read)"
```

- [ ] **Step 3: Run the licence check.** `uv run pytest tests/unit/test_check_licenses.py -v` → PASS. Then `uv run python tools/check_licenses.py` → exit 0. Any package it reports gets an override entry only after reading its real licence file, with the URL in `source`; a GPL or AGPL result stops the task and goes to Aydin.

- [ ] **Step 4: Write the failing arithmetic-lint tests.** `tests/unit/test_check_price_arithmetic.py`:

```python
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
```

- [ ] **Step 5: Write the arithmetic lint.** `tools/check_price_arithmetic.py`:

```python
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
```

Run: `uv run pytest tests/unit/test_check_price_arithmetic.py -v` → PASS; `uv run python tools/check_price_arithmetic.py` → exit 0.

- [ ] **Step 6: The notices generator.** `tools/gen_notices.py` writes `THIRD_PARTY_NOTICES.txt` at the repository root, in this order, each part under a heading with the package name, version and SPDX expression:
  1. every runtime Python distribution from the same `uv export --no-dev` list as the licence check, with the full text of each file in its `dist.files` whose name starts with `LICENSE`, `LICENCE`, `COPYING` or `NOTICE` (Apache-2.0 `NOTICE` texts are reproduced in full);
  2. every file named `LICENSE*`, `NOTICE*` or `ThirdPartyNotices*` under the installed `playwright/driver/` folder (the bundled Node.js and Playwright core);
  3. every `*LICENSE*` file under the installed `webview/lib/` folder (Microsoft's WebView2 SDK);
  4. PyInstaller's licence text section that contains the bootloader exception, from the installed `PyInstaller` distribution;
  5. for each production npm package, its `LICENSE` file from `web/node_modules/<name>/`.

  A unit test builds notices from a fake distribution in `tmp_path` and checks that the licence text and heading appear. Run `uv run python tools/gen_notices.py` and open the result: it must name `fastapi`, `uvicorn`, `pywebview`, `playwright` and `react`.

  The notices ship in every wheel (§17, §18). In `hatch_build.py`, after the screens build (so only for non-editable wheel builds), require `THIRD_PARTY_NOTICES.txt` at the repository root, raising `RuntimeError("run tools/gen_notices.py before building a wheel")` if it is missing, and add it with `build_data["force_include"][str(notices)] = "mihenk/THIRD_PARTY_NOTICES.txt"`. Run `uv run python tools/gen_notices.py && uv build --wheel` and list the wheel: it contains `mihenk/THIRD_PARTY_NOTICES.txt`. Add `hatch_build.py` to this task's files.

- [ ] **Step 7: Commit.** `git add -A && git commit -m "Licence allow-list, notices generator, price-arithmetic lint"`

### Task 0.8: Installers for Windows and macOS

**Files:**
- Create: `packaging/mihenk.spec`, `packaging/windows/mihenk.iss`, `packaging/macos/make_dmg.sh`, `docs/decisions/NNNN-packaging.md`
- Modify: `pyproject.toml` and `uv.lock` (the pythonnet pin)
- Where each step runs: Step 1's Windows half runs on this machine. Step 1's macOS half, Step 2 and Step 4 need macOS, and Step 3 needs Inno Setup and installs the app, so they run in CI (Task 0.9) after Aydin's go to push. Until then the decision record marks them "pending CI".

**Interfaces:**
- Consumes: `mihenk.app.launcher.main`, `--smoke` (Task 0.5); the built screens (Task 0.4); `THIRD_PARTY_NOTICES.txt` (Task 0.7).
- Produces: `dist/mihenk/` (onedir) and `dist/mihenk-<version>-windows-x64-setup.exe` on Windows; `dist/mihenk.app` and `dist/mihenk-<version>-macos-arm64.dmg` on macOS.

- [ ] **Step 1: The PyInstaller spec.** `packaging/mihenk.spec`:

```python
# Build from the repository root: uv run pyinstaller packaging/mihenk.spec --noconfirm
import os
import sys

from PyInstaller.utils.hooks import collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 (SPECPATH is set by PyInstaller)
sys.path.insert(0, os.path.join(ROOT, "src"))
from mihenk import __version__  # noqa: E402

datas = collect_data_files("mihenk", includes=["web_dist/**"])
datas += [
    (os.path.join(ROOT, name), ".")
    for name in ("LICENSE", "NOTICE", "EVALUATION.md", "THIRD_PARTY_NOTICES.txt")
]

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "src", "mihenk", "__main__.py")],
    pathex=[os.path.join(ROOT, "src")],
    datas=datas,
    # pywebview would otherwise pull in every GUI backend it finds; Qt is GPL (§18).
    # pydantic.mypy drags in the dev-only type checker and cffi's build shim drags in
    # setuptools; neither runs in the app, and neither is in the notices.
    excludes=[
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "qtpy",
        "gi",
        "tkinter",
        "mypy",
        "mypy_extensions",
        "pydantic.mypy",
        "setuptools",
    ],
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="mihenk",
    console=False,
    upx=False,
    codesign_identity=None,
    # A crash must end the process, not wait on an error dialog (CI would hang).
    disable_windowed_traceback=True,
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="mihenk")  # noqa: F821
if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name="mihenk.app",
        bundle_identifier="io.github.maydinidil.mihenk",
        info_plist={"CFBundleShortVersionString": __version__, "NSHighResolutionCapable": True},
    )
```

Run (after `cd web && npm run build` and `uv run python tools/gen_notices.py`): `uv run pyinstaller packaging/mihenk.spec --noconfirm`
Expected: `dist/mihenk/` exists. Then the release check on the unpacked build: Windows `Start-Process dist\mihenk\mihenk.exe -ArgumentList '--smoke' -Wait -PassThru` exits 0; macOS `dist/mihenk.app/Contents/MacOS/mihenk --smoke; echo $?` prints 0.

Once the Windows smoke check passes, pin the pair it used: read the `pythonnet` and `clr_loader` versions from `uv.lock` and add `"pythonnet==<that version>; sys_platform == 'win32'"` and `"clr_loader==<that version>; sys_platform == 'win32'"` to `dependencies` (§17: pywebview does not pin pythonnet, and a brand-new release can break the loader). Run `uv lock` and the smoke check again.

- [ ] **Step 2: The macOS spike.** pywebview documents py2app, not PyInstaller, for macOS (§22). If Step 1's macOS smoke run fails, try in this order and stop at the first that passes the smoke check: (a) adjust the spec (hidden imports for `webview.platforms.cocoa`, `pyobjc` frameworks), (b) py2app, (c) Nuitka (AGPL compiler with a runtime exception for built programs; read `LICENSE-RUNTIME.txt` first). Write the outcome, the error output of each failed attempt and the chosen tool in `docs/decisions/NNNN-packaging.md`. A change of tool is reported to Aydin before stage 1 starts.

- [ ] **Step 3: The Windows installer.** `packaging/windows/mihenk.iss` (Inno Setup 6). The `AppId` GUID below was generated once for mihenk and must never change, or Windows treats later versions as a different app:

```ini
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{83DA634F-AEEA-484A-BAFD-E5ADED97378D}
AppName=mihenk
AppVersion={#AppVersion}
AppPublisher=maydinidil
DefaultDirName={localappdata}\Programs\mihenk
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist
OutputBaseFilename=mihenk-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes

[Files]
Source: "..\..\dist\mihenk\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: not WebView2Installed

[Icons]
Name: "{autoprograms}\mihenk"; Filename: "{app}\mihenk.exe"

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Installing Microsoft WebView2..."; Flags: waituntilterminated; Check: not WebView2Installed
Filename: "{app}\mihenk.exe"; Description: "Start mihenk"; Flags: nowait postinstall skipifsilent

[Code]
function HasVersion(Root: Integer; Key: String): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(Root, Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0');
end;

function WebView2Installed(): Boolean;
var
  Key: String;
begin
  Key := '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  Result := HasVersion(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\' + Key)
         or HasVersion(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\' + Key);
end;
```

`AppId={{...}` with the opening brace doubled is Inno Setup's escaping for a literal brace. The WebView2 bootstrapper is downloaded at build time from Microsoft (`https://go.microsoft.com/fwlink/p/?LinkId=2124703`) into `packaging/windows/MicrosoftEdgeWebview2Setup.exe`, which `.gitignore` must list.

Run on Windows (in CI: `build.yml` installs Inno Setup with `choco install innosetup -y` when `iscc` is not on the runner): `iscc /DAppVersion=0.0.1 packaging\windows\mihenk.iss` → `dist\mihenk-0.0.1-windows-x64-setup.exe`. Install it on the CI machine silently (`/VERYSILENT /SUPPRESSMSGBOXES`), then run `"%LOCALAPPDATA%\Programs\mihenk\mihenk.exe" --smoke` → exit 0. Record the Inno Setup version and its licence in `docs/decisions/NNNN-packaging.md`.

- [ ] **Step 4: The macOS disk image.** `packaging/macos/make_dmg.sh`:

```sh
#!/bin/sh
# Usage: packaging/macos/make_dmg.sh 0.0.1
set -eu
version="$1"
hdiutil create -volname "mihenk" -srcfolder "dist/mihenk.app" -ov -format UDZO \
  "dist/mihenk-${version}-macos-arm64.dmg"
```

Run: `sh packaging/macos/make_dmg.sh 0.0.1` → the `.dmg` exists and mounts.

- [ ] **Step 5: Commit.** `git add -A && git commit -m "PyInstaller onedir builds, Windows installer, macOS disk image"`

### Task 0.9: Continuous integration

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/workflows/build.yml`

**Interfaces:** Consumes every check command from `CLAUDE.md`, and Task 0.8's packaging.

- [ ] **Step 1: `ci.yml`.** Triggers: `push` and `pull_request`. Matrix `os: [windows-latest, macos-latest]` (`macos-latest` runners are Apple silicon). Permissions: `contents: read`. Every third-party action is pinned to a full commit SHA, with the version in a comment. Steps:
  1. `actions/checkout`
  2. `astral-sh/setup-uv`, then `uv sync --locked`
  3. `actions/setup-node` with `node-version: 24`, `cache: npm`, `cache-dependency-path: web/package-lock.json`; `npm ci` in `web/`
  4. `uv run ruff format --check .` and `uv run ruff check .`
  5. `uv run mypy`
  6. in `web/`: `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`
  7. API types: `uv run python tools/dump_openapi.py`, `npm run gen:api` in `web/`, then `git diff --exit-code web/openapi.json web/src/api/schema.ts`
  8. `uv run pytest` with `env: MIHENK_REQUIRE_BROWSER: "1"` (both runner images include Chrome)
  9. `uv run python tools/check_licenses.py`
  10. `uv run python tools/check_price_arithmetic.py`

- [ ] **Step 2: `build.yml`.** Triggers: `workflow_dispatch`, a nightly `schedule` on `main`, and pushes to branches named `release/*` (§16). Same matrix and setup, then: `npm run build` in `web/`; `uv run python tools/gen_notices.py`; `uv build --wheel` (macOS job only, one wheel is enough); `uv run pyinstaller packaging/mihenk.spec --noconfirm`; on Windows, download the WebView2 bootstrapper, run `iscc`, install silently and run the installed app with `--smoke` through `Start-Process ... -Wait -PassThru`, failing on a non-zero exit code; on macOS, run the `.app` with `--smoke`, then `make_dmg.sh`. Upload the installer, the `.dmg` and the wheel with `actions/upload-artifact`.

  If a hosted runner cannot open a window at all (the smoke step times out with no window error), record it in `docs/decisions/NNNN-packaging.md`, keep the job's build steps, and replace the window smoke with `--browser`-free server smoke (start the onedir app with `--smoke --smoke-timeout 5` and accept exit code 1 only if the log shows the server started). Aydin then runs the window smoke by hand for each release.

- [ ] **Step 3: Prove it on the branch.** Pushing needs Aydin's go: ask for it, push `stage-0`, and run `build.yml` by `workflow_dispatch`. Expected: `ci.yml` green on both systems; `build.yml` produces three artifacts.

- [ ] **Step 4: Commit** any fixes found by CI. `git add -A && git commit -m "CI: checks on Windows and macOS, installer builds with release check"`

### Task 0.10: The remaining spikes

**Files:**
- Create: `docs/decisions/NNNN-uv-install-from-url.md`, `docs/decisions/NNNN-microsoft-store.md`

- [ ] **Step 1: uv from a wheel URL.** Build the wheel (`uv run python tools/gen_notices.py && uv build --wheel`), serve `dist/` with `uv run python -m http.server 8765 --bind 127.0.0.1 --directory dist`, and in another shell, with `UV_TOOL_DIR` and `UV_TOOL_BIN_DIR` both set to folders inside a fresh temporary directory (so nothing lands in Aydin's own tools), run `uv tool install http://127.0.0.1:8765/mihenk-0.0.1-py3-none-any.whl`, then the installed `mihenk --smoke` from that bin folder (exit 0), then `uv tool uninstall mihenk` and delete the temporary directory. This downloads mihenk's dependencies from PyPI on Aydin's machine, which installing a planned package allows. Record the commands and the result. If uv refuses a URL, record the fallback (download the wheel, then `uv tool install ./mihenk-...whl`) for the README.
- [ ] **Step 2: Microsoft Store route (desk research only, nothing is submitted).** From Microsoft's own documentation, answer: can a PyInstaller onedir app be packaged as MSIX for the Store; do Store policies allow an app that drives the user's browser and offers to download Playwright's Chromium; what account is needed and at what cost for an individual in the Netherlands. Give a go or no-go recommendation with sources. Aydin decides before 1.0.
- [ ] **Step 3: Commit.** `git add -A && git commit -m "Spike records: uv from URL, Microsoft Store"`

### Task 0.11: Outside this repository (needs Aydin)

Done outside this repository: the private record is updated to point here. Nothing in this repository changes.

### Stage 0 done

- [ ] `ci.yml` green on Windows and macOS; `build.yml` produced the installer, the `.dmg` and the wheel; the installed app passes `--smoke` (or the hosted-runner fallback is recorded and Aydin's manual smoke passed).
- [ ] Decision records exist for the name and repository, packaging, uv install from a URL and the Microsoft Store route (plus the test client, if Task 0.3 needed one).
- [ ] Ask Aydin whether to open the stage-0 pull request.

---

## Stage 1: capture, no LLM

Done when (§21): every trap page is captured by every method it is meant for, with snapshots, hashes and locale markers, and Aydin has run `mihenk capture` on one real pricing page of Aydin's choosing and opened its snapshot folder. Work on branch `stage-1`, made from `stage-0`.

### Task 1.1: The trap pages (capture level)

**Files:**
- Create: `tests/fixtures/pages/<name>/page.html` and `tests/fixtures/pages/<name>/expect.json` for each page below; `tests/helpers/pages.py`

**Interfaces:** Produces `load_expectations(name: str) -> dict[str, Any]` and `serve_page(site: LocalSite, name: str) -> str` (returns the page URL) in `tests/helpers/pages.py`. The values, quotes and offsets for extraction are added in stage 2; stage 1 expectations are about capture only.

Every page is written for this repository, in our own words and markup, with made-up company names (Acme Mail, Northwind Hosting, Contoso CRM and similar). `expect.json` has this shape in stage 1 (Tasks 1.5, 1.6, 1.8 and 1.9 read it; every key except `methods` and `status` is optional):

```json
{
  "methods": ["fetch", "render"],
  "status": "ok",
  "fetch_text_contains": ["€9 / month"],
  "fetch_text_lacks": ["€99"],
  "render_text_contains": ["€9 / month"],
  "states": [
    {"label": "annual", "actions": [], "text_contains": ["€24 / month, billed yearly"], "text_lacks": ["billed monthly"]},
    {"label": "monthly", "actions": [{"kind": "click_text", "text": "Monthly"}], "text_contains": ["€29 / month, billed monthly"], "text_lacks": []}
  ],
  "structured": [{"kind": "jsonld", "problem": null}],
  "locale": {
    "html_lang": "nl",
    "currency_symbols": ["€"],
    "currency_codes": ["EUR"],
    "vat_phrases": [{"language": "nl", "kind": "excl", "phrase": "excl. btw"}]
  }
}
```

- `methods`: the `Method` values (`fetch`, `render`, `render_interact`) this page is meant to be captured by; Task 1.9's parametrised test captures every page by each. A page with `states` lists `render_interact`.
- `status`: the `CaptureStatus` value expected for every listed method (`needs_human` for `bot-wall`, `ok` otherwise).
- `states[].actions`: the recipe's own action JSON (`click_text`, `click_selector`, `select_option`), so a test builds `State(**state)` from it after dropping `text_contains` and `text_lacks`.
- `structured`: one entry per expected block, in page order: a `StructuredKind` value and the expected `problem` (`null`, `"too_large"`, or a prefix such as `"invalid_json"`).
- `locale`: compared field by field with `markers_to_json(detect_locale_markers(...))`; a field left out is not compared. `vat_phrases` lists `VatPhrase` fields.

| Page | What it tests |
|---|---|
| `static-table` | Prices in a plain HTML table; fetch finds them |
| `js-only-prices` | Prices written by a script after load; fetch text lacks them, render text has them |
| `billing-toggle` | Defaults to annual ("€24 / month, billed yearly"); clicking the button "Monthly" shows "€29 / month, billed monthly". States `annual` (no actions) and `monthly` (click text "Monthly") |
| `jsonld-currency-mismatch` | JSON-LD offer says `"priceCurrency": "USD"` while the page shows € |
| `next-data` | A `__NEXT_DATA__` blob holding the plans |
| `split-digits` | A price split across inline spans (`<span>€</span><span>4</span><span>9</span>`); text must read `€49` |
| `svg-noise` | An SVG icon whose path data contains `405`, and a real price `405 Kč`; text holds the price once and no path data |
| `never-idle` | A script polls `/poll` every 300 ms and `/poll` answers after 5 s, so the network never goes idle |
| `windows-1254` | Turkish page encoded as windows-1254, `<meta charset="windows-1254">`, no charset in the HTTP header; contains `Aylık 199 TL` and `Fiyatlara KDV dahildir` |
| `huge-blob` | An `application/json` script block of 3 MB |
| `bot-wall` | Served with status 403, title `Just a moment...`, a `/cdn-cgi/challenge-platform/` script URL |
| `vat-en`, `vat-nl`, `vat-de`, `vat-fr`, `vat-es`, `vat-it`, `vat-tr` | One VAT wording per language, with matching `<html lang>`, for example `incl. VAT`, `excl. btw`, `inkl. 19 % MwSt.`, `prix HT`, `IVA incluido`, `+ IVA`, `KDV DAHİL` |

- [ ] **Step 1:** Write the pages and their `expect.json` files, and `tests/helpers/pages.py` with `load_expectations` (reads `expect.json`) and `serve_page` (registers `page.html` on the `LocalSite` at `/<name>`; for `windows-1254` it sends `Content-Type: text/html` with no charset; for `bot-wall` status 403; for `never-idle` it also registers `/poll` with `delay_s=5`).
- [ ] **Step 2:** Add `tests/unit/test_trap_pages.py`: every folder has both files, every `expect.json` parses and has `methods` (non-empty, each a `Method` value) and `status` (a `CaptureStatus` value), and no page references a host other than its own. Read each page as bytes (the `windows-1254` page is not UTF-8) and find every `http://` or `https://` URL; the only ones allowed are the namespace identifiers `https://schema.org` (and paths under it) and `http://www.w3.org/2000/svg`, which browsers never fetch.
- [ ] **Step 3:** Run `uv run pytest tests/unit/test_trap_pages.py -v` → PASS. Commit: `git add -A && git commit -m "Trap pages for capture"`.

### Task 1.2: `robots.txt` decisions

**Files:**
- Create: `src/mihenk/capture/robots.py`
- Modify: `pyproject.toml` (add `"protego>=0.7.0,<0.8"`; `uv lock`)
- Test: `tests/unit/test_robots.py` (`tests/integration/test_robots_fetch.py` comes with Task 1.4, which owns the fetching)

**Interfaces:**
- Produces: `USER_AGENT_TOKEN = "mihenk"`, `MAX_ROBOTS_BYTES = 524288`, `MAX_REDIRECTS = 5`, `RobotsFetch(status: int | None, body: bytes | None, detail: str)`, `RobotsDecision(allowed: bool, reason: str)`, `robots_url(page_url: str) -> str`, `decide(fetch: RobotsFetch, page_url: str) -> RobotsDecision`, `RobotsGate(fetch_robots: Callable[[str], RobotsFetch])` with `.check(page_url) -> RobotsDecision` (one fetch per robots URL per gate). The HTTP fetch of `robots.txt` is `fetch_robots(client, url) -> RobotsFetch` in Task 1.4.

- [ ] **Step 1: Write the failing tests.** `tests/unit/test_robots.py`:

```python
import pytest

from mihenk.capture.robots import RobotsFetch, RobotsGate, decide, robots_url

PAGE = "https://shop.example/pricing"


def ok(text: str) -> RobotsFetch:
    return RobotsFetch(200, text.encode("utf-8"), "fetched")


def test_robots_url() -> None:
    assert robots_url("https://shop.example:8443/a/b?c=d") == "https://shop.example:8443/robots.txt"


def test_disallowed_path() -> None:
    decision = decide(ok("User-agent: *\nDisallow: /pricing\n"), PAGE)
    assert not decision.allowed
    assert "rules" in decision.reason


def test_specific_group_beats_star() -> None:
    text = "User-agent: mihenk\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    assert not decide(ok(text), PAGE).allowed


def test_longest_match_wins() -> None:
    assert decide(ok("User-agent: *\nDisallow: /pri\nAllow: /pricing\n"), PAGE).allowed


def test_allow_wins_a_tie() -> None:
    assert decide(ok("User-agent: *\nDisallow: /pricing\nAllow: /pricing\n"), PAGE).allowed


def test_wildcard_and_end_anchor() -> None:
    text = "User-agent: *\nDisallow: /*.json$\n"
    assert not decide(ok(text), "https://shop.example/plans.json").allowed
    assert decide(ok(text), "https://shop.example/plans.jsonx").allowed


def test_html_soft_404_robots_allows() -> None:
    html = "<!doctype html><html><body><h1>Page not found</h1></body></html>"
    assert decide(ok(html), PAGE).allowed


@pytest.mark.parametrize("status", [404, 410, 400])
def test_missing_robots_allows(status: int) -> None:
    assert decide(RobotsFetch(status, b"", "fetched"), PAGE).allowed


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_refusals_and_errors_disallow(status: int) -> None:
    decision = decide(RobotsFetch(status, b"", "fetched"), PAGE)
    assert not decision.allowed
    assert str(status) in decision.reason


def test_unreachable_disallows() -> None:
    decision = decide(RobotsFetch(None, None, "unreachable: connection refused"), PAGE)
    assert not decision.allowed
    assert "unreachable" in decision.reason


def test_gate_fetches_once_per_site() -> None:
    calls: list[str] = []

    def fetch(url: str) -> RobotsFetch:
        calls.append(url)
        return ok("User-agent: *\nAllow: /\n")

    gate = RobotsGate(fetch)
    assert gate.check("https://shop.example/a").allowed
    assert gate.check("https://shop.example/b").allowed
    assert calls == ["https://shop.example/robots.txt"]
```

Run: `uv run pytest tests/unit/test_robots.py -v` → FAIL (`ModuleNotFoundError`).

- [ ] **Step 2: Write the module.** `src/mihenk/capture/robots.py`:

```python
"""robots.txt decisions (design §8.2): RFC 9309 matching through protego.

mihenk is stricter than RFC 9309 in three places, as a politeness choice: 401 and 403 are
treated as disallow-all (the RFC allows everything on any 4xx), 429 disallows for the run,
and more than five redirects counts as unreachable. Every decision carries its reason.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from protego import Protego

USER_AGENT_TOKEN = "mihenk"
MAX_ROBOTS_BYTES = 512 * 1024
MAX_REDIRECTS = 5


@dataclass(frozen=True)
class RobotsFetch:
    status: int | None
    body: bytes | None
    detail: str


@dataclass(frozen=True)
class RobotsDecision:
    allowed: bool
    reason: str


def robots_url(page_url: str) -> str:
    parts = urlsplit(page_url)
    return urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))


def decide(fetch: RobotsFetch, page_url: str) -> RobotsDecision:
    status = fetch.status
    if status is None:
        return RobotsDecision(False, f"robots.txt {fetch.detail}; treated as disallow-all")
    if 200 <= status < 300:
        text = (fetch.body or b"")[:MAX_ROBOTS_BYTES].decode("utf-8", errors="replace")
        if Protego.parse(text).can_fetch(page_url, USER_AGENT_TOKEN):
            return RobotsDecision(True, "allowed by the robots.txt rules")
        return RobotsDecision(False, "disallowed by the robots.txt rules")
    if status in (401, 403):
        return RobotsDecision(
            False, f"robots.txt answered {status}; mihenk treats this as disallow-all"
        )
    if status == 429:
        return RobotsDecision(False, "robots.txt answered 429 (slow down); disallowed for this run")
    if 400 <= status < 500:
        return RobotsDecision(True, f"no robots.txt (answered {status}); allowed")
    return RobotsDecision(False, f"robots.txt answered {status}; treated as disallow-all")


class RobotsGate:
    """One robots.txt fetch per site per run."""

    def __init__(self, fetch_robots: Callable[[str], RobotsFetch]) -> None:
        self._fetch = fetch_robots
        self._cache: dict[str, RobotsFetch] = {}

    def check(self, page_url: str) -> RobotsDecision:
        url = robots_url(page_url)
        if url not in self._cache:
            self._cache[url] = self._fetch(url)
        return decide(self._cache[url], page_url)
```

- [ ] **Step 3: Run.** `uv run pytest tests/unit/test_robots.py -v` → PASS. If `test_allow_wins_a_tie` fails, protego does not follow RFC 9309's tie rule: record protego's actual behaviour in `docs/decisions/NNNN-robots-ties.md`, change the test to that behaviour with a comment pointing at the record, and do not patch protego.
- [ ] **Step 4: Commit.** `git add -A && git commit -m "robots.txt decisions with protego, stricter on 401/403/429"`

The integration tests that fetch `robots.txt` over HTTP (`test_robots_redirect_loop_disallows`, redirects across hosts, oversize files) live in Task 1.4, where the HTTP client is built.

### Task 1.3: Pacing per site

**Files:**
- Create: `src/mihenk/capture/pace.py`
- Test: `tests/unit/test_pace.py`

**Interfaces:** Produces `Pace(min_interval_s: float = 2.0, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep)` with `.wait(host: str) -> float` (seconds slept) and `host_key(url: str) -> str`.

- [ ] **Step 1: Write the failing tests.** `tests/unit/test_pace.py`:

```python
from mihenk.capture.pace import Pace, host_key


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_first_request_does_not_wait() -> None:
    fake = FakeClock()
    assert Pace(2.0, fake.clock, fake.sleep).wait("a.example") == 0.0


def test_second_request_to_the_same_site_waits_the_rest_of_the_interval() -> None:
    fake = FakeClock()
    pace = Pace(2.0, fake.clock, fake.sleep)
    pace.wait("a.example")
    fake.now += 0.5
    assert pace.wait("a.example") == 1.5


def test_different_sites_do_not_wait_for_each_other() -> None:
    fake = FakeClock()
    pace = Pace(2.0, fake.clock, fake.sleep)
    pace.wait("a.example")
    assert pace.wait("b.example") == 0.0


def test_host_key_ignores_case_and_path() -> None:
    assert host_key("https://Shop.Example:8443/x?y") == "shop.example:8443"
```

- [ ] **Step 2: Write the module.** `src/mihenk/capture/pace.py`:

```python
"""At most one request per site every min_interval_s seconds (design §8.2).

Used only on the capture thread, so it needs no lock.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from urllib.parse import urlsplit


def host_key(url: str) -> str:
    return urlsplit(url).netloc.lower()


class Pace:
    def __init__(
        self,
        min_interval_s: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._min = min_interval_s
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}

    def wait(self, host: str) -> float:
        now = self._clock()
        last = self._last.get(host)
        delay = 0.0 if last is None else max(0.0, last + self._min - now)
        if delay > 0:
            self._sleep(delay)
        self._last[host] = now + delay
        return delay
```

- [ ] **Step 3: Run** `uv run pytest tests/unit/test_pace.py -v` → PASS. **Commit:** `git add -A && git commit -m "Per-site pacing"`

### Task 1.4: Fetching pages and `robots.txt` over HTTP

**Files:**
- Create: `src/mihenk/capture/models.py`, `src/mihenk/capture/fetch.py`, `docs/decisions/NNNN-http-client.md`
- Modify: `pyproject.toml` (add `httpx2` with a floor at the version the LLM SDKs use, or `httpx` if Step 1 says so)
- Test: `tests/unit/test_decode.py`, `tests/integration/test_fetch.py`, `tests/integration/test_robots_fetch.py`

**Interfaces:**
- Produces in `models.py`: `class Method(StrEnum): FETCH, RENDER, RENDER_INTERACT` (values `"fetch"`, `"render"`, `"render_interact"`); `class CaptureStatus(StrEnum): OK, BLOCKED_BY_ROBOTS, HTTP_ERROR, TIMEOUT, NEEDS_HUMAN, TOO_LARGE, BROWSER_UNAVAILABLE, ACTION_FAILED` (values are the snake-case names); `SAFE_SEGMENT` (the pattern every run id, page key and state label must match, used by snapshots and recipes).
- Produces in `fetch.py`: `MAX_PAGE_BYTES = 15 * 1024 * 1024`; `KEPT_HEADERS = ("content-type", "content-language", "server", "cf-mitigated", "cf-ray")`; `decode_html(body: bytes, content_type: str | None) -> tuple[str, str]`; `FetchedPage(url, final_url, status: int, headers: Mapping[str, str], raw: bytes, html: str, encoding: str)`; `FetchFailure(status: CaptureStatus, detail: str)` (an exception); `make_client(accept_language: str, timeout_s: float = 30.0)`; `fetch_page(client, url) -> FetchedPage`; `fetch_robots(client, url) -> RobotsFetch`.

- [ ] **Step 1: Confirm the HTTP client.** Both LLM SDKs depend on `httpx2` (§22). Read `httpx2`'s README and confirm: the import name; `Client(headers=..., timeout=..., follow_redirects=..., max_redirects=...)`; `client.stream("GET", url)` with `iter_bytes()`; the exceptions `TimeoutException`, `TooManyRedirects`, `TransportError`. The code below imports it as `import httpx2 as http`. If `httpx2` differs from this API, use `httpx` instead (same API) and record why. Write `docs/decisions/NNNN-http-client.md` either way.

- [ ] **Step 2: Write the failing decoding tests.** `tests/unit/test_decode.py`:

```python
from mihenk.capture.fetch import decode_html

TURKISH = "<meta charset='windows-1254'><p>Aylık 199 TL, Fiyatlara KDV dahildir. İstanbul şube</p>"


def test_header_charset_wins() -> None:
    text, encoding = decode_html("€29".encode("utf-8"), "text/html; charset=utf-8")
    assert (text, encoding) == ("€29", "utf-8")


def test_decode_windows_1254_from_meta() -> None:
    text, encoding = decode_html(TURKISH.encode("cp1254"), "text/html")
    assert encoding == "cp1254"
    assert "Aylık 199 TL" in text
    assert "İstanbul şube" in text


def test_utf8_bom() -> None:
    text, encoding = decode_html(b"\xef\xbb\xbf<p>\xe2\x82\xac9</p>", None)
    assert text == "<p>€9</p>"
    assert encoding == "utf-8-sig"


def test_unknown_charset_falls_back_to_utf8() -> None:
    text, encoding = decode_html("€9".encode("utf-8"), "text/html; charset=no-such-thing")
    assert (text, encoding) == ("€9", "utf-8")
```

- [ ] **Step 3: Write the models and the fetch module.** `src/mihenk/capture/models.py`:

```python
import re
from enum import StrEnum

# Run ids, page keys and state labels become folder names: lowercase, no separators.
SAFE_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class Method(StrEnum):
    FETCH = "fetch"
    RENDER = "render"
    RENDER_INTERACT = "render_interact"


class CaptureStatus(StrEnum):
    OK = "ok"
    BLOCKED_BY_ROBOTS = "blocked_by_robots"
    HTTP_ERROR = "http_error"
    TIMEOUT = "timeout"
    NEEDS_HUMAN = "needs_human"
    TOO_LARGE = "too_large"
    BROWSER_UNAVAILABLE = "browser_unavailable"
    ACTION_FAILED = "action_failed"
```

`src/mihenk/capture/fetch.py`:

```python
"""Plain HTTP capture (design §8.3) and the robots.txt fetch (§8.2)."""

from __future__ import annotations

import codecs
import re
from collections.abc import Mapping
from dataclasses import dataclass

import httpx2 as http

from mihenk import __version__
from mihenk.capture.models import CaptureStatus
from mihenk.capture.robots import MAX_REDIRECTS, MAX_ROBOTS_BYTES, RobotsFetch

MAX_PAGE_BYTES = 15 * 1024 * 1024
KEPT_HEADERS = ("content-type", "content-language", "server", "cf-mitigated", "cf-ray")
_META_CHARSET = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""", re.IGNORECASE
)
_HEADER_CHARSET = re.compile(r"charset\s*=\s*\"?([A-Za-z0-9_.:-]+)", re.IGNORECASE)


class FetchFailure(Exception):
    def __init__(self, status: CaptureStatus, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class FetchedPage:
    url: str
    final_url: str
    status: int
    headers: Mapping[str, str]
    raw: bytes
    html: str
    encoding: str


def _codec(name: str | None) -> str | None:
    if not name:
        return None
    try:
        return codecs.lookup(name).name
    except LookupError:
        return None


def decode_html(body: bytes, content_type: str | None) -> tuple[str, str]:
    """Text and the encoding used: a BOM, then the HTTP charset, then <meta charset>, then UTF-8."""
    if body.startswith(codecs.BOM_UTF8):
        return body.decode("utf-8-sig", errors="replace"), "utf-8-sig"
    header = _HEADER_CHARSET.search(content_type or "")
    meta = _META_CHARSET.search(body[:4096])
    for candidate in (
        _codec(header.group(1) if header else None),
        _codec(meta.group(1).decode("ascii", "ignore") if meta else None),
        "utf-8",
    ):
        if candidate is not None:
            return body.decode(candidate, errors="replace"), candidate
    raise AssertionError("utf-8 always exists")


def make_client(accept_language: str, timeout_s: float = 30.0) -> http.Client:
    return http.Client(
        headers={
            "User-Agent": f"mihenk/{__version__} (+https://github.com/maydinidil/mihenk)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": accept_language,
        },
        timeout=timeout_s,
        follow_redirects=True,
        max_redirects=MAX_REDIRECTS,
    )


def _read_capped(response: http.Response, cap: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > cap:
            raise FetchFailure(CaptureStatus.TOO_LARGE, f"larger than {cap} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_page(client: http.Client, url: str) -> FetchedPage:
    try:
        with client.stream("GET", url) as response:
            raw = _read_capped(response, MAX_PAGE_BYTES)
            headers = {k: response.headers[k] for k in KEPT_HEADERS if k in response.headers}
            html, encoding = decode_html(raw, response.headers.get("content-type"))
            return FetchedPage(
                url, str(response.url), response.status_code, headers, raw, html, encoding
            )
    except http.TimeoutException as exc:
        raise FetchFailure(CaptureStatus.TIMEOUT, f"timed out: {exc}") from exc
    except http.TooManyRedirects as exc:
        raise FetchFailure(CaptureStatus.HTTP_ERROR, "more than 5 redirects") from exc
    except http.TransportError as exc:
        raise FetchFailure(CaptureStatus.HTTP_ERROR, f"unreachable: {exc}") from exc


def fetch_robots(client: http.Client, url: str) -> RobotsFetch:
    try:
        with client.stream("GET", url) as response:
            body = b""
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) >= MAX_ROBOTS_BYTES:
                    break  # RFC 9309 lets crawlers stop parsing after the limit
            return RobotsFetch(response.status_code, body[:MAX_ROBOTS_BYTES], "fetched")
    except http.TooManyRedirects:
        return RobotsFetch(None, None, "more than 5 redirects")
    except (http.TimeoutException, http.TransportError) as exc:
        return RobotsFetch(None, None, f"unreachable: {type(exc).__name__}")
```

- [ ] **Step 4: Write the failing HTTP tests.** `tests/integration/test_fetch.py`: serve `static-table`, `windows-1254` and an oversize page (16 MB body) on `LocalSite`; assert `fetch_page` returns status 200 and the expected text for the first, the Turkish text for the second, and that the third raises `FetchFailure` with status `TOO_LARGE` (`test_page_over_size_cap_fails_as_too_large`). Also: a route with `delay_s=2` and a client with `timeout_s=0.5` raises `FetchFailure` with `TIMEOUT`; a 404 route returns a `FetchedPage` with status 404 (the decision about errors belongs to Task 1.9).

`tests/integration/test_robots_fetch.py`:

```python
from mihenk.capture.fetch import fetch_robots, make_client
from mihenk.capture.robots import RobotsGate, decide


def test_robots_redirect_loop_disallows(site) -> None:  # type: ignore[no-untyped-def]
    site.redirect("/robots.txt", "/robots-a")
    site.redirect("/robots-a", "/robots-b")
    site.redirect("/robots-b", "/robots-a")
    with make_client("en") as client:
        fetched = fetch_robots(client, site.url("/robots.txt"))
    assert fetched.status is None
    assert not decide(fetched, site.url("/pricing")).allowed


def test_robots_redirect_is_followed(site) -> None:  # type: ignore[no-untyped-def]
    site.redirect("/robots.txt", "/real-robots.txt")
    site.add("/real-robots.txt", "User-agent: *\nDisallow: /pricing\n", content_type="text/plain")
    with make_client("en") as client:
        gate = RobotsGate(lambda url: fetch_robots(client, url))
        assert not gate.check(site.url("/pricing")).allowed
        assert gate.check(site.url("/about")).allowed


def test_missing_robots_allows(site) -> None:  # type: ignore[no-untyped-def]
    with make_client("en") as client:
        assert decide(fetch_robots(client, site.url("/robots.txt")), site.url("/x")).allowed
```

- [ ] **Step 5: Run.** `uv run pytest tests/unit/test_decode.py tests/integration/test_fetch.py tests/integration/test_robots_fetch.py -v` → PASS. Then `uv run mypy && uv run ruff check .`.
- [ ] **Step 6: Commit.** `git add -A && git commit -m "HTTP fetch with charset handling, size cap and robots.txt fetch"`

### Task 1.5: Canonical text and structured data

**Files:**
- Create: `src/mihenk/trim/__init__.py`, `src/mihenk/trim/text.py`, `src/mihenk/trim/structured.py`
- Modify: `pyproject.toml` (add `"beautifulsoup4>=4.12,<5"`; `uv lock`; rerun the licence check)
- Test: `tests/unit/test_text.py`, `tests/unit/test_structured.py`

**Interfaces:**
- Produces: `canonical_text(raw: str) -> str` (the one form of page text stored and later shown to the LLM; quotes are matched against it); `html_to_text(html: str) -> str` (fetch route); `MAX_BLOCK_BYTES = 2_000_000`; `class StructuredKind(StrEnum): JSONLD, NEXT_DATA, NUXT_DATA, JSON_SCRIPT`; `StructuredBlock(kind, index: int, script_id: str | None, raw: str | None, size_bytes: int, parsed: object | None, problem: str | None)`; `extract_structured(html: str) -> list[StructuredBlock]`; `block_to_json(block) -> dict[str, object]`.

- [ ] **Step 1: Write the failing tests.** `tests/unit/test_text.py`:

```python
from mihenk.trim.text import canonical_text, html_to_text


def test_canonical_text_collapses_spaces_and_keeps_line_breaks() -> None:
    raw = "Pro\u00a0plan  \t €\u202f49 \r\n\r\n\r\n\r\nper month\u200b"
    assert canonical_text(raw) == "Pro plan € 49\n\nper month\n"


def test_canonical_text_is_nfc_and_keeps_turkish_and_minus_sign() -> None:
    decomposed = "I\u0307stanbul \u22125%"
    assert canonical_text(decomposed) == "İstanbul −5%\n"


def test_inline_spans_join_without_spaces() -> None:
    html = "<p>Price: <span>€</span><span>4</span><span>9</span></p>"
    assert html_to_text(html) == "Price: €49\n"


def test_blocks_become_lines_and_scripts_are_dropped() -> None:
    html = "<div>Basic</div><div>€9 / month</div><script>var x = 405;</script><style>p{}</style>"
    assert html_to_text(html) == "Basic\n€9 / month\n"


def test_source_newlines_inside_text_are_spaces() -> None:
    assert html_to_text("<p>billed\n   yearly</p>") == "billed yearly\n"


def test_svg_path_numbers_do_not_appear() -> None:
    html = '<svg><path d="M405 10 L405 20"/></svg><p>405 Kč</p>'
    assert html_to_text(html) == "405 Kč\n"


def test_hidden_elements_are_dropped() -> None:
    assert html_to_text("<p hidden>€99</p><p>€9</p>") == "€9\n"
```

`tests/unit/test_structured.py`: JSON-LD inside `<!-- -->` and `//<![CDATA[ ... //]]>` wrappers parses; invalid JSON gives `problem` starting with `invalid_json`; `__NEXT_DATA__` is kind `next_data`; a script of `type="text/javascript"` is ignored; `test_huge_json_block_is_marked_too_large` builds a 3 MB `application/json` block and expects `problem == "too_large"`, `raw is None`, `parsed is None`, `size_bytes > MAX_BLOCK_BYTES`; the `jsonld-currency-mismatch` and `next-data` trap pages give the kinds in their `expect.json`.

- [ ] **Step 2: Write `trim/text.py`.**

```python
"""The one canonical form of page text (design §8.5, §8.6).

Every snapshot stores this form, the LLM sees exactly this form, and quotes are matched
against it. Normalising here, once, before anyone quotes from it, is safe; normalising the
page at match time is not (§8.6).
"""

from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup, NavigableString, Tag
from bs4.element import CData, Comment, Declaration, Doctype, ProcessingInstruction

_HSPACE = re.compile(r"[ \t\f\v\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]+")
_INVISIBLE = re.compile(r"[\u200b\ufeff]")
_BLOCK = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "caption",
        "dd",
        "details",
        "dialog",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "summary",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
)
_SKIP = frozenset({"script", "style", "noscript", "template", "head", "iframe", "object", "path"})
_NOT_TEXT = (Comment, CData, Declaration, Doctype, ProcessingInstruction)


def canonical_text(raw: str) -> str:
    text = unicodedata.normalize("NFC", raw).replace("\r\n", "\n").replace("\r", "\n")
    text = _INVISIBLE.sub("", text)
    lines = [_HSPACE.sub(" ", line).strip() for line in text.split("\n")]
    joined = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return joined + "\n" if joined else ""


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    parts: list[str] = []

    def walk(node: Tag, in_pre: bool) -> None:
        for child in node.children:
            if isinstance(child, _NOT_TEXT):
                continue
            if isinstance(child, NavigableString):
                parts.append(str(child) if in_pre else re.sub(r"\s+", " ", str(child)))
                continue
            if not isinstance(child, Tag):
                continue
            name = child.name.lower()
            if name in _SKIP or child.has_attr("hidden"):
                continue
            if name == "br":
                parts.append("\n")
                continue
            block = name in _BLOCK
            if block:
                parts.append("\n")
            walk(child, in_pre or name == "pre")
            if block:
                parts.append("\n")

    walk(soup, in_pre=False)
    # One line per block: block edges never produce blank lines on the fetch route.
    return canonical_text(re.sub(r"\n[ \t]*(?:\n[ \t]*)+", "\n", "".join(parts)))
```

- [ ] **Step 3: Write `trim/structured.py`.**

```python
"""JSON-LD and framework data found in a page (design §8.3). No extruct (§22)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

from bs4 import BeautifulSoup, Tag

MAX_BLOCK_BYTES = 2_000_000
_WRAPPERS = (("<!--", "-->"), ("//<![CDATA[", "//]]>"), ("<![CDATA[", "]]>"))


class StructuredKind(StrEnum):
    JSONLD = "jsonld"
    NEXT_DATA = "next_data"
    NUXT_DATA = "nuxt_data"
    JSON_SCRIPT = "json_script"


@dataclass(frozen=True)
class StructuredBlock:
    kind: StructuredKind
    index: int
    script_id: str | None
    raw: str | None
    size_bytes: int
    parsed: object | None
    problem: str | None


def _kind(script: Tag) -> StructuredKind | None:
    script_type = str(script.get("type") or "").strip().lower()
    script_id = script.get("id")
    if script_type == "application/ld+json":
        return StructuredKind.JSONLD
    if script_id == "__NEXT_DATA__":
        return StructuredKind.NEXT_DATA
    if script_id == "__NUXT_DATA__":
        return StructuredKind.NUXT_DATA
    if script_type == "application/json":
        return StructuredKind.JSON_SCRIPT
    return None


def _strip_wrappers(raw: str) -> str:
    text = raw.strip()
    for prefix, suffix in _WRAPPERS:
        if text.startswith(prefix) and text.endswith(suffix):
            text = text[len(prefix) : -len(suffix)].strip()
    return text


def extract_structured(html: str) -> list[StructuredBlock]:
    blocks: list[StructuredBlock] = []
    for index, script in enumerate(BeautifulSoup(html, "html.parser").find_all("script")):
        if not isinstance(script, Tag):
            continue
        kind = _kind(script)
        if kind is None:
            continue
        raw = script.get_text()
        script_id = script.get("id")
        sid = script_id if isinstance(script_id, str) else None
        size = len(raw.encode("utf-8"))
        if size > MAX_BLOCK_BYTES:
            blocks.append(StructuredBlock(kind, index, sid, None, size, None, "too_large"))
            continue
        try:
            parsed: object = json.loads(_strip_wrappers(raw))
        except json.JSONDecodeError as exc:
            blocks.append(
                StructuredBlock(kind, index, sid, raw, size, None, f"invalid_json: {exc.msg}")
            )
        else:
            blocks.append(StructuredBlock(kind, index, sid, raw, size, parsed, None))
    return blocks


def block_to_json(block: StructuredBlock) -> dict[str, object]:
    return {
        "kind": block.kind.value,
        "index": block.index,
        "script_id": block.script_id,
        "size_bytes": block.size_bytes,
        "problem": block.problem,
        "parsed": block.parsed,
        "raw": block.raw if block.parsed is None else None,
    }
```

- [ ] **Step 4: Run** `uv run pytest tests/unit/test_text.py tests/unit/test_structured.py -v && uv run mypy && uv run python tools/check_licenses.py` → all pass. **Commit:** `git add -A && git commit -m "Canonical text and structured data extraction"`

### Task 1.6: Locale markers

**Files:**
- Create: `src/mihenk/capture/locale.py`
- Test: `tests/unit/test_locale.py`

**Interfaces:** Produces `VatPhrase(language: str, kind: Literal["incl", "excl"], phrase: str)`, `LocaleMarkers(html_lang: str | None, content_language: str | None, currency_symbols: tuple[str, ...], currency_codes: tuple[str, ...], vat_phrases: tuple[VatPhrase, ...])`, `detect_locale_markers(html: str, text: str, headers: Mapping[str, str]) -> LocaleMarkers`, `markers_to_json(m) -> dict[str, object]`. Markers are signals for flags in stage 2, never values.

- [ ] **Step 1: Write the failing tests.** `tests/unit/test_locale.py`:

```python
import pytest

from mihenk.capture.locale import detect_locale_markers


def markers(text: str, html: str = "<html lang='en'>", headers: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
    return detect_locale_markers(html, text, headers or {})


@pytest.mark.parametrize(
    ("text", "language", "kind"),
    [
        ("€29 incl. VAT", "en", "incl"),
        ("£19 + VAT", "en", "excl"),
        ("€25 excl. btw", "nl", "excl"),
        ("€25 inclusief btw", "nl", "incl"),
        ("29 € inkl. 19 % MwSt.", "de", "incl"),
        ("29 € zzgl. MwSt.", "de", "excl"),
        ("29 € HT", "fr", "excl"),
        ("29 € TTC", "fr", "incl"),
        ("29 € IVA incluido", "es", "incl"),
        ("29 € IVA no incluido", "es", "excl"),
        ("29 € + IVA", "it", "excl"),
        ("Fiyatlara KDV dahildir", "tr", "incl"),
        ("199 TL KDV DAHİL", "tr", "incl"),
        ("199 TL + KDV", "tr", "excl"),
        ("199 TL KDV HARİÇ", "tr", "excl"),
    ],
)
def test_vat_phrases(text: str, language: str, kind: str) -> None:
    found = markers(text).vat_phrases
    assert (language, kind) in {(p.language, p.kind) for p in found}


def test_iva_no_incluido_is_not_reported_as_included() -> None:
    kinds = {(p.language, p.kind) for p in markers("29 € IVA no incluido").vat_phrases}
    assert ("es", "incl") not in kinds


def test_symbols_and_codes_next_to_numbers() -> None:
    found = markers("Basic €9, Pro 29 USD, Team 405 Kč, Try it free")
    assert "€" in found.currency_symbols
    assert "Kč" in found.currency_symbols
    assert found.currency_codes == ("USD",)


def test_language_signals() -> None:
    found = markers(
        "x", html="<html lang='nl-NL'><body>x</body></html>", headers={"content-language": "nl"}
    )
    assert (found.html_lang, found.content_language) == ("nl-NL", "nl")
```

- [ ] **Step 2: Write the module.** `src/mihenk/capture/locale.py`:

```python
"""Locale markers: signals about which country's page this is (design §8.3, §8.8).

Turkish letters are spelled out in character classes rather than relying on case-insensitive
matching, because İ and ı do not fold to i like English letters do.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from bs4 import BeautifulSoup

VatKind = Literal["incl", "excl"]


@dataclass(frozen=True)
class VatPhrase:
    language: str
    kind: VatKind
    phrase: str


@dataclass(frozen=True)
class LocaleMarkers:
    html_lang: str | None
    content_language: str | None
    currency_symbols: tuple[str, ...]
    currency_codes: tuple[str, ...]
    vat_phrases: tuple[VatPhrase, ...]


_I = re.IGNORECASE
_VAT: tuple[tuple[str, VatKind, re.Pattern[str]], ...] = (
    ("en", "excl", re.compile(r"(?:\b(?:excl(?:\.|uding)?|ex\.?|plus)\s*|\+\s*)VAT\b", _I)),
    ("en", "incl", re.compile(r"\b(?:incl(?:\.|uding)?|inc\.?)\s*VAT\b|\bVAT\s+included\b", _I)),
    ("nl", "excl", re.compile(r"(?:\b(?:excl(?:\.|usief)?|ex\.?)\s*|\+\s*)btw\b", _I)),
    ("nl", "incl", re.compile(r"\b(?:incl(?:\.|usief)?)\s*btw\b", _I)),
    (
        "de",
        "excl",
        re.compile(
            r"\b(?:zzgl\.?|zuzüglich|exkl\.?|exklusive)\s*(?:\d{1,2}\s*%\s*)?(?:MwSt|USt)\b", _I
        ),
    ),
    ("de", "incl", re.compile(r"\b(?:inkl\.?|inklusive)\s*(?:\d{1,2}\s*%\s*)?(?:MwSt|USt)\b", _I)),
    ("fr", "excl", re.compile(r"(?<![\w-])HT(?![\w-])")),
    ("fr", "incl", re.compile(r"(?<![\w-])TTC(?![\w-])")),
    (
        "es",
        "excl",
        re.compile(r"(?:\bmás\s*|\+\s*)IVA\b|\bIVA\s+no\s+incluido\b|\bsin\s+IVA\b", _I),
    ),
    ("es", "incl", re.compile(r"\bIVA\s+incluido\b", _I)),
    ("it", "excl", re.compile(r"(?:\bpiù\s*|\+\s*)IVA\b|\bIVA\s+esclusa\b", _I)),
    ("it", "incl", re.compile(r"\bIVA\s+(?:inclusa|compresa)\b|\bincl\.?\s*IVA\b", _I)),
    ("tr", "excl", re.compile(r"\+\s*KDV\b|\bKDV\s*har[iİı][çÇcC]|\bKDV['’]?s[iİı]z\b", _I)),
    ("tr", "incl", re.compile(r"\bKDV\s*d[aâ]h[iİı]l", _I)),
)
_FREE_SYMBOLS = ("€", "£", "¥", "₺", "₹", "₽", "₩", "$")
_WORD_SYMBOLS = ("zł", "Kč", "kr", "CHF", "TL", "R$")
_CODES = (
    "EUR",
    "USD",
    "GBP",
    "CHF",
    "SEK",
    "NOK",
    "DKK",
    "PLN",
    "CZK",
    "HUF",
    "RON",
    "TRY",
    "JPY",
    "CNY",
    "INR",
    "AUD",
    "CAD",
    "NZD",
    "BRL",
    "MXN",
    "ZAR",
)
_NUM = r"\d[\d.,\u00a0 ]*"


def _beside_number(token: str, text: str) -> bool:
    escaped = re.escape(token)
    pattern = rf"(?:{_NUM}\s?{escaped}(?![\w]))|(?:(?<![\w]){escaped}\s?\d)"
    return re.search(pattern, text) is not None


def detect_locale_markers(html: str, text: str, headers: Mapping[str, str]) -> LocaleMarkers:
    root = BeautifulSoup(html[:200_000], "html.parser").find("html")
    lang = root.get("lang") if root is not None and hasattr(root, "get") else None
    symbols = sorted(
        {s for s in _FREE_SYMBOLS if s in text}
        | {s for s in _WORD_SYMBOLS if _beside_number(s, text)}
    )
    codes = sorted(c for c in _CODES if _beside_number(c, text))
    phrases: list[VatPhrase] = []
    for language, kind, pattern in _VAT:
        phrases.extend(VatPhrase(language, kind, m.group(0)) for m in pattern.finditer(text))
    return LocaleMarkers(
        html_lang=lang if isinstance(lang, str) else None,
        content_language={k.lower(): v for k, v in headers.items()}.get("content-language"),
        currency_symbols=tuple(symbols),
        currency_codes=tuple(codes),
        vat_phrases=tuple(phrases),
    )


def markers_to_json(markers: LocaleMarkers) -> dict[str, object]:
    return {
        "html_lang": markers.html_lang,
        "content_language": markers.content_language,
        "currency_symbols": list(markers.currency_symbols),
        "currency_codes": list(markers.currency_codes),
        "vat_phrases": [
            {"language": p.language, "kind": p.kind, "phrase": p.phrase}
            for p in markers.vat_phrases
        ],
    }
```

- [ ] **Step 3: Run** `uv run pytest tests/unit/test_locale.py -v` → PASS. If a Turkish case fails, fix the character class, not the test. Also run the seven `vat-*` trap pages through `html_to_text` and `detect_locale_markers` and compare with their `expect.json` in a parametrised test. **Commit:** `git add -A && git commit -m "Locale markers with VAT wording in 7 languages"`

### Task 1.7: Snapshots

**Files:**
- Create: `src/mihenk/capture/snapshot.py`
- Test: `tests/unit/test_snapshot.py`

**Interfaces:**
- Consumes: `Method` (1.4), `StructuredBlock`, `block_to_json` (1.5), `LocaleMarkers`, `markers_to_json` (1.6).
- Consumes also: `SAFE_SEGMENT` (1.4).
- Produces: `new_run_id(now: datetime) -> str`; `SnapshotInput(run_id, page_key, state_label, url, final_url, http_status: int | None, method: Method, captured_at: datetime, html: str, raw_bytes: bytes | None, encoding: str | None, text: str, structured: Sequence[StructuredBlock], screenshot_png: bytes | None, locale: LocaleMarkers, collection_country: str)`; `SnapshotRef(path: Path, html_sha256: str, text_sha256: str, raw_sha256: str | None)`; `SnapshotExists`; `write_snapshot(root: Path, snap: SnapshotInput) -> SnapshotRef`.

- [ ] **Step 1: Write the failing tests.** `tests/unit/test_snapshot.py`:

```python
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mihenk.capture.locale import LocaleMarkers
from mihenk.capture.models import Method
from mihenk.capture.snapshot import SnapshotExists, SnapshotInput, new_run_id, write_snapshot

NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
NO_MARKERS = LocaleMarkers(None, None, (), (), ())


def snap(run_id: str = "20261008t120000z-abc123", **changes: object) -> SnapshotInput:
    base = dict(
        run_id=run_id,
        page_key="acme-pricing",
        state_label="default",
        url="https://acme.example/p",
        final_url="https://acme.example/p",
        http_status=200,
        method=Method.FETCH,
        captured_at=NOW,
        html="<p>Aylık 199 TL</p>",
        raw_bytes="<p>Aylık 199 TL</p>".encode("cp1254"),
        encoding="cp1254",
        text="Aylık 199 TL\n",
        structured=[],
        screenshot_png=None,
        locale=NO_MARKERS,
        collection_country="NL",
    )
    base.update(changes)
    return SnapshotInput(**base)  # type: ignore[arg-type]


def test_run_ids_are_safe_and_sortable() -> None:
    run_id = new_run_id(NOW)
    assert run_id.startswith("20261008t120000z-")
    assert run_id == run_id.lower()


def test_hashes_match_the_files(tmp_path: Path) -> None:
    ref = write_snapshot(tmp_path, snap())
    assert hashlib.sha256((ref.path / "page.html").read_bytes()).hexdigest() == ref.html_sha256
    assert hashlib.sha256((ref.path / "text.txt").read_bytes()).hexdigest() == ref.text_sha256
    assert hashlib.sha256((ref.path / "page.raw").read_bytes()).hexdigest() == ref.raw_sha256
    meta = json.loads((ref.path / "meta.json").read_text("utf-8"))
    assert meta["captured_at"] == "2026-10-08T12:00:00Z"
    assert meta["collection_country"] == "NL"


def test_turkish_text_survives_snapshot(tmp_path: Path) -> None:
    ref = write_snapshot(tmp_path, snap(text="Aylık 199 TL, KDV DAHİL, İstanbul şube\n"))
    assert (
        ref.path / "text.txt"
    ).read_bytes() == "Aylık 199 TL, KDV DAHİL, İstanbul şube\n".encode("utf-8")


def test_snapshots_are_never_overwritten(tmp_path: Path) -> None:
    write_snapshot(tmp_path, snap())
    with pytest.raises(SnapshotExists):
        write_snapshot(tmp_path, snap())


@pytest.mark.parametrize("bad", ["../escape", "Upper", "a/b", "", "x" * 65])
def test_unsafe_path_segments_are_refused(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError, match="unsafe"):
        write_snapshot(tmp_path, snap(page_key=bad))


def test_naive_time_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="UTC"):
        write_snapshot(tmp_path, snap(captured_at=datetime(2026, 10, 8, 12, 0, 0)))  # noqa: DTZ001


def test_snapshot_in_path_with_spaces_and_turkish_letters(tmp_path: Path) -> None:
    root = tmp_path / "Ayşe Yılmaz" / "mihenk data" / "snapshots"
    ref = write_snapshot(root, snap())
    assert (ref.path / "meta.json").is_file()


def test_no_temporary_folder_is_left_after_a_failure(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        write_snapshot(tmp_path, snap(screenshot_png=object()))
    run_folder = tmp_path / "20261008t120000z-abc123" / "acme-pricing"
    assert not any(p.name.startswith(".tmp-") for p in run_folder.iterdir())
```

- [ ] **Step 2: Write the module.** `src/mihenk/capture/snapshot.py`:

```python
"""Immutable snapshot folders (design §8.3): written once, never modified.

Layout: <root>/<run_id>/<page_key>/<state_label>/ with page.html (UTF-8), page.raw (the bytes
as received, fetch route only), text.txt (canonical text), structured.json, screenshot.png
(render routes only) and meta.json. The folder appears atomically, by renaming a temporary one.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mihenk import __version__
from mihenk.capture.locale import LocaleMarkers, markers_to_json
from mihenk.capture.models import SAFE_SEGMENT, Method
from mihenk.trim.structured import StructuredBlock, block_to_json


class SnapshotExists(FileExistsError):
    pass


@dataclass(frozen=True)
class SnapshotInput:
    run_id: str
    page_key: str
    state_label: str
    url: str
    final_url: str
    http_status: int | None
    method: Method
    captured_at: datetime
    html: str
    raw_bytes: bytes | None
    encoding: str | None
    text: str
    structured: Sequence[StructuredBlock]
    screenshot_png: bytes | None
    locale: LocaleMarkers
    collection_country: str


@dataclass(frozen=True)
class SnapshotRef:
    path: Path
    html_sha256: str
    text_sha256: str
    raw_sha256: str | None


def new_run_id(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y%m%dt%H%M%Sz") + "-" + secrets.token_hex(3)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_snapshot(root: Path, snap: SnapshotInput) -> SnapshotRef:
    for segment in (snap.run_id, snap.page_key, snap.state_label):
        if not SAFE_SEGMENT.fullmatch(segment):
            raise ValueError(f"unsafe snapshot path segment: {segment!r}")
    if snap.captured_at.utcoffset() != timedelta(0):
        raise ValueError("captured_at must be a UTC time")
    target = root / snap.run_id / snap.page_key / snap.state_label
    if target.exists():
        raise SnapshotExists(str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".tmp-", dir=target.parent))
    try:
        html_bytes = snap.html.encode("utf-8")
        text_bytes = snap.text.encode("utf-8")
        (tmp / "page.html").write_bytes(html_bytes)
        (tmp / "text.txt").write_bytes(text_bytes)
        if snap.raw_bytes is not None:
            (tmp / "page.raw").write_bytes(snap.raw_bytes)
        if snap.screenshot_png is not None:
            (tmp / "screenshot.png").write_bytes(snap.screenshot_png)
        structured = [block_to_json(block) for block in snap.structured]
        (tmp / "structured.json").write_text(
            json.dumps(structured, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        ref = SnapshotRef(
            target,
            _sha256(html_bytes),
            _sha256(text_bytes),
            _sha256(snap.raw_bytes) if snap.raw_bytes is not None else None,
        )
        meta = {
            "app_version": __version__,
            "run_id": snap.run_id,
            "page_key": snap.page_key,
            "state_label": snap.state_label,
            "url": snap.url,
            "final_url": snap.final_url,
            "http_status": snap.http_status,
            "method": snap.method.value,
            "captured_at": snap.captured_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "encoding": snap.encoding,
            "collection_country": snap.collection_country,
            "locale": markers_to_json(snap.locale),
            "html_sha256": ref.html_sha256,
            "text_sha256": ref.text_sha256,
            "raw_sha256": ref.raw_sha256,
        }
        (tmp / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
        tmp.rename(target)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return ref
```

The last test passes `object()` as the screenshot, which fails inside `write_bytes` and must leave no `.tmp-` folder behind.

- [ ] **Step 3: Run** `uv run pytest tests/unit/test_snapshot.py -v && uv run mypy` → PASS. **Commit:** `git add -A && git commit -m "Immutable snapshot folders with hashes"`

### Task 1.8: Recipes and rendering

**Files:**
- Create: `src/mihenk/capture/recipe.py`, `src/mihenk/capture/render.py`
- Test: `tests/unit/test_recipe.py`, `tests/integration/test_render.py`

**Interfaces:**
- Consumes: `Method` (1.4), `canonical_text` (1.5), `LaunchedBrowser` (0.6).
- Produces: `ClickText(kind="click_text", text: str, exact: bool = True)`, `ClickSelector(kind="click_selector", selector: str)`, `SelectOption(kind="select_option", selector: str, value: str)`, `Action` (discriminated union on `kind`), `State(label: str, actions: list[Action] = [])`, `Recipe(method: Method, states: list[State])` with validation (fetch and render: exactly one state with no actions; render_interact: at least one state; labels unique and matching `SAFE_SEGMENT`); `RenderSettings(navigation_timeout_s: float = 30.0, idle_cap_s: float = 5.0, settle_s: float = 0.5, locale: str = "en-GB")`; `RenderedState(label, final_url, status: int | None, headers: Mapping[str, str], html: str, visible_text: str, screenshot_png: bytes)`; `StateFailure(label, status: CaptureStatus, detail: str)`; `render_states(browser: Browser, url: str, recipe: Recipe, settings: RenderSettings, before_navigation: Callable[[], object]) -> list[RenderedState | StateFailure]`.

- [ ] **Step 1: Write the failing recipe tests.** `tests/unit/test_recipe.py`: a fetch recipe with two states is refused; a fetch recipe with one state that has an action is refused; a `render_interact` recipe with states `annual` (no actions) and `monthly` (`click_text "Monthly"`) is accepted and round-trips through `model_dump_json()` and `model_validate_json()`; duplicate labels are refused; label `"Monthly"` (capital) is refused.

- [ ] **Step 2: Write `recipe.py`.**

```python
"""Recipes: how to capture a page and which states to capture (design §8.3). Data, not code."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mihenk.capture.models import SAFE_SEGMENT, Method


class ClickText(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["click_text"] = "click_text"
    text: str = Field(min_length=1, max_length=200)
    exact: bool = True


class ClickSelector(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["click_selector"] = "click_selector"
    selector: str = Field(min_length=1, max_length=500)


class SelectOption(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["select_option"] = "select_option"
    selector: str = Field(min_length=1, max_length=500)
    value: str


Action = Annotated[ClickText | ClickSelector | SelectOption, Field(discriminator="kind")]


class State(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    label: str = Field(pattern=SAFE_SEGMENT.pattern)
    actions: list[Action] = Field(default_factory=list)


class Recipe(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    method: Method
    states: list[State] = Field(min_length=1)

    @model_validator(mode="after")
    def _rules(self) -> Recipe:
        labels = [state.label for state in self.states]
        if len(set(labels)) != len(labels):
            raise ValueError("state labels must be unique")
        if self.method is not Method.RENDER_INTERACT and (
            len(self.states) != 1 or self.states[0].actions
        ):
            raise ValueError(f"a {self.method.value} recipe has exactly one state and no actions")
        return self
```

Run the recipe tests → PASS.

- [ ] **Step 3: Write the failing render tests.** `tests/integration/test_render.py`, all marked `@pytest.mark.browser`, using `site` and `browser` (the fixture is a `LaunchedBrowser`: pass `browser.browser` to `render_states`):
  - `test_js_only_prices_need_render`: `render_states` on `js-only-prices` with `Recipe(method=RENDER, states=[State(label="default")])` returns one `RenderedState` whose `visible_text` contains every string in `render_text_contains`.
  - `test_billing_toggle_states`: the `billing-toggle` recipe returns two states; `annual` text contains `€24 / month, billed yearly` and lacks `billed monthly`; `monthly` text contains `€29 / month, billed monthly`.
  - `test_render_finishes_on_never_idle_page`: rendering `never-idle` with `RenderSettings(idle_cap_s=2.0)` returns a `RenderedState` and the call takes less than `navigation_timeout_s` (measure with `time.monotonic()`; assert under 15 s).
  - `test_missing_toggle_is_an_action_failure`: a state that clicks text `"Quarterly"` on `billing-toggle` gives `StateFailure` with status `ACTION_FAILED` and the other state still succeeds.
  - `test_before_navigation_is_called_per_state`: the callback is called once per state.
  - `test_each_call_uses_a_fresh_context`: after one render sets a cookie through `document.cookie`, a second render on the same site does not see it.

- [ ] **Step 4: Write `render.py`.**

```python
"""Rendering pages in the installed browser (design §8.3).

Each call opens a fresh browser context (no cookies carried over, downloads off) and closes
it. Each state is a fresh navigation followed by its actions. Pages that never go
network-idle are normal: the idle wait is capped and the capture continues.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from playwright.sync_api import Browser, Page
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from mihenk.capture.models import CaptureStatus
from mihenk.capture.recipe import Action, ClickSelector, ClickText, Recipe, SelectOption
from mihenk.trim.text import canonical_text


@dataclass(frozen=True)
class RenderSettings:
    navigation_timeout_s: float = 30.0
    idle_cap_s: float = 5.0
    settle_s: float = 0.5
    locale: str = "en-GB"


@dataclass(frozen=True)
class RenderedState:
    label: str
    final_url: str
    status: int | None
    headers: Mapping[str, str]
    html: str
    visible_text: str
    screenshot_png: bytes


@dataclass(frozen=True)
class StateFailure:
    label: str
    status: CaptureStatus
    detail: str


class _ActionFailed(Exception):
    pass


def _settle(page: Page, settings: RenderSettings) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=settings.idle_cap_s * 1000)
    except PlaywrightTimeoutError:
        pass
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(settings.settle_s * 1000)


def _perform(page: Page, action: Action) -> None:
    try:
        match action:
            case ClickText(text=text, exact=exact):
                page.get_by_text(text, exact=exact).first.click()
            case ClickSelector(selector=selector):
                page.locator(selector).first.click()
            case SelectOption(selector=selector, value=value):
                page.locator(selector).first.select_option(value)
    except PlaywrightError as exc:
        raise _ActionFailed(f"{action.kind}: {exc}") from exc


def render_states(
    browser: Browser,
    url: str,
    recipe: Recipe,
    settings: RenderSettings,
    before_navigation: Callable[[], object],
) -> list[RenderedState | StateFailure]:
    context = browser.new_context(accept_downloads=False, locale=settings.locale)
    results: list[RenderedState | StateFailure] = []
    try:
        page = context.new_page()
        page.set_default_timeout(settings.navigation_timeout_s * 1000)
        for state in recipe.states:
            before_navigation()
            try:
                response = page.goto(url, wait_until="domcontentloaded")
                _settle(page, settings)
                for action in state.actions:
                    _perform(page, action)
                    _settle(page, settings)
            except _ActionFailed as exc:
                results.append(StateFailure(state.label, CaptureStatus.ACTION_FAILED, str(exc)))
                continue
            except PlaywrightTimeoutError as exc:
                results.append(StateFailure(state.label, CaptureStatus.TIMEOUT, str(exc)))
                continue
            results.append(
                RenderedState(
                    label=state.label,
                    final_url=page.url,
                    status=response.status if response is not None else None,
                    headers=dict(response.headers) if response is not None else {},
                    html=page.content(),
                    visible_text=canonical_text(page.inner_text("body")),
                    screenshot_png=page.screenshot(full_page=True),
                )
            )
    finally:
        context.close()
    return results
```

- [ ] **Step 5: Run** `uv run pytest tests/unit/test_recipe.py tests/integration/test_render.py -v && uv run mypy` → PASS. **Commit:** `git add -A && git commit -m "Recipes and rendering with capped idle waits"`

### Task 1.9: Capturing a page end to end, and the CLI

**Files:**
- Create: `src/mihenk/capture/walls.py`, `src/mihenk/capture/run.py`, `src/mihenk/cli.py`
- Modify: `src/mihenk/app/launcher.py` (`main` hands `capture` and `install-browser` to `cli.main`)
- Test: `tests/unit/test_walls.py`, `tests/integration/test_capture_page.py`, `tests/integration/test_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 1.2 to 1.8, `launch_browser` (0.6).
- Produces: `looks_like_bot_wall(status: int | None, html: str) -> bool`; `PageSpec(key: str, url: str, recipe: Recipe, respect_robots: bool = True)`; `CaptureResult(page_key, state_label, method: Method, status: CaptureStatus, detail: str, snapshot: SnapshotRef | None)`; `RunContext(run_id, snapshots_root: Path, collection_country: str, robots: RobotsGate, pace: Pace, http_client, browser: Browser | None, render: RenderSettings, now: Callable[[], datetime])`; `capture_page(spec: PageSpec, ctx: RunContext) -> list[CaptureResult]`; `cli.main(argv: Sequence[str]) -> int`.

- [ ] **Step 1: Bot walls.** `tests/unit/test_walls.py`: the `bot-wall` trap page with status 403 is a wall; `<title>Access Denied</title>` with status 403 is a wall; a normal pricing page with status 200 that contains the word "captcha" in a footer link is not; `/cdn-cgi/challenge-platform/` anywhere is a wall. `src/mihenk/capture/walls.py`:

```python
"""Recognising bot walls, so they are recorded as needs_human (design §15)."""

from __future__ import annotations

import re

_MARKERS = (
    "/cdn-cgi/challenge-platform",
    "cf-chl-",
    "_incapsula_resource",
    "px-captcha",
    "captcha-delivery",
)
_TITLES = ("just a moment", "attention required", "access denied", "please verify you are a human")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def looks_like_bot_wall(status: int | None, html: str) -> bool:
    head = html[:200_000].lower()
    if any(marker in head for marker in _MARKERS):
        return True
    match = _TITLE.search(head)
    title = match.group(1).strip() if match else ""
    return status in (403, 429, 503) and any(title.startswith(t) for t in _TITLES)
```

- [ ] **Step 2: Write the failing orchestration tests.** `tests/integration/test_capture_page.py`, using `site`, `browser` (where rendering is needed; `RunContext.browser` takes `browser.browser`), a `RunContext` with `Pace(0.0)`, a `RobotsGate` over `fetch_robots`, `collection_country="NL"` and `snapshots_root=tmp_path`:
  - `static-table` by fetch → one result, status `ok`, a snapshot whose `text.txt` contains the `fetch_text_contains` strings and whose `meta.json` has `method == "fetch"`.
  - `js-only-prices` by fetch → status `ok` but `text.txt` lacks the prices; by render → status `ok` and contains them.
  - `billing-toggle` by `render_interact` → two results, `annual` and `monthly`, two snapshot folders, each with a `screenshot.png`.
  - `bot-wall` by fetch → status `needs_human`, with a snapshot kept as evidence.
  - a page under `Disallow: /` in `robots.txt` → status `blocked_by_robots`, no snapshot, and `site.hits` contains `/robots.txt` but not the page; the same with `respect_robots=False` → status `ok`.
  - a page answering 500 → status `http_error`, snapshot kept, `detail` naming 500.
  - render with `browser=None` → status `browser_unavailable` for each state.
  - `huge-blob` → status `ok` and `structured.json` shows `problem: "too_large"`.
  - `windows-1254` → `meta.json` has `encoding: "cp1254"`, `text.txt` contains `Aylık 199 TL`, and the locale markers include a Turkish `incl` VAT phrase.
  - `test_every_trap_page_by_its_methods`: parametrised over every trap page and every method in its `expect.json` `methods` (render methods browser-marked); `capture_page` returns the expected `status` for every state, each `ok` result has a snapshot whose files match the `SnapshotRef` SHA-256 values and whose `meta.json` holds `locale`, and for `fetch` the text contains `fetch_text_contains` and lacks `fetch_text_lacks`. This is the stage 1 "done" check.

- [ ] **Step 3: Write `run.py`.** The robots gate is built by the caller with a fetch function that paces first (`lambda url: (ctx.pace.wait(host_key(url)), fetch_robots(client, url))[1]` in the CLI), so the `robots.txt` request is paced like any other.

```python
"""Capturing one page end to end (design §8.2, §8.3, §15). Runs on the capture thread only."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser

from mihenk.capture.fetch import FetchFailure, fetch_page
from mihenk.capture.locale import detect_locale_markers
from mihenk.capture.models import CaptureStatus, Method
from mihenk.capture.pace import Pace, host_key
from mihenk.capture.recipe import Recipe
from mihenk.capture.render import RenderedState, RenderSettings, render_states
from mihenk.capture.robots import RobotsGate
from mihenk.capture.snapshot import SnapshotInput, SnapshotRef, write_snapshot
from mihenk.capture.walls import looks_like_bot_wall
from mihenk.trim.structured import extract_structured
from mihenk.trim.text import html_to_text


@dataclass(frozen=True)
class PageSpec:
    key: str
    url: str
    recipe: Recipe
    respect_robots: bool = True


@dataclass(frozen=True)
class CaptureResult:
    page_key: str
    state_label: str
    method: Method
    status: CaptureStatus
    detail: str
    snapshot: SnapshotRef | None


@dataclass
class RunContext:
    run_id: str
    snapshots_root: Path
    collection_country: str
    robots: RobotsGate
    pace: Pace
    http_client: Any  # the Client from fetch.make_client
    browser: Browser | None
    render: RenderSettings
    now: Callable[[], datetime]  # must return a UTC time


def _status_for(http_status: int | None, html: str) -> tuple[CaptureStatus, str]:
    if looks_like_bot_wall(http_status, html):
        return CaptureStatus.NEEDS_HUMAN, "the page is a bot check; a person has to open it"
    if http_status is not None and http_status >= 400:
        return CaptureStatus.HTTP_ERROR, f"answered {http_status}"
    return CaptureStatus.OK, "captured"


def capture_page(spec: PageSpec, ctx: RunContext) -> list[CaptureResult]:
    method = spec.recipe.method
    if spec.respect_robots:
        decision = ctx.robots.check(spec.url)
        if not decision.allowed:
            return [
                CaptureResult(
                    spec.key,
                    state.label,
                    method,
                    CaptureStatus.BLOCKED_BY_ROBOTS,
                    decision.reason,
                    None,
                )
                for state in spec.recipe.states
            ]
    if method is Method.FETCH:
        return [_capture_fetch(spec, ctx)]
    return _capture_render(spec, ctx)


def _capture_fetch(spec: PageSpec, ctx: RunContext) -> CaptureResult:
    label = spec.recipe.states[0].label
    ctx.pace.wait(host_key(spec.url))
    try:
        page = fetch_page(ctx.http_client, spec.url)
    except FetchFailure as exc:
        return CaptureResult(spec.key, label, Method.FETCH, exc.status, exc.detail, None)
    text = html_to_text(page.html)
    ref = write_snapshot(
        ctx.snapshots_root,
        SnapshotInput(
            run_id=ctx.run_id,
            page_key=spec.key,
            state_label=label,
            url=spec.url,
            final_url=page.final_url,
            http_status=page.status,
            method=Method.FETCH,
            captured_at=ctx.now(),
            html=page.html,
            raw_bytes=page.raw,
            encoding=page.encoding,
            text=text,
            structured=extract_structured(page.html),
            screenshot_png=None,
            locale=detect_locale_markers(page.html, text, page.headers),
            collection_country=ctx.collection_country,
        ),
    )
    status, detail = _status_for(page.status, page.html)
    return CaptureResult(spec.key, label, Method.FETCH, status, detail, ref)


def _capture_render(spec: PageSpec, ctx: RunContext) -> list[CaptureResult]:
    method = spec.recipe.method
    if ctx.browser is None:
        return [
            CaptureResult(
                spec.key,
                state.label,
                method,
                CaptureStatus.BROWSER_UNAVAILABLE,
                "no Chrome, Edge or downloaded Chromium was found",
                None,
            )
            for state in spec.recipe.states
        ]
    host = host_key(spec.url)
    results: list[CaptureResult] = []
    for outcome in render_states(
        ctx.browser, spec.url, spec.recipe, ctx.render, lambda: ctx.pace.wait(host)
    ):
        if not isinstance(outcome, RenderedState):
            results.append(
                CaptureResult(spec.key, outcome.label, method, outcome.status, outcome.detail, None)
            )
            continue
        ref = write_snapshot(
            ctx.snapshots_root,
            SnapshotInput(
                run_id=ctx.run_id,
                page_key=spec.key,
                state_label=outcome.label,
                url=spec.url,
                final_url=outcome.final_url,
                http_status=outcome.status,
                method=method,
                captured_at=ctx.now(),
                html=outcome.html,
                raw_bytes=None,
                encoding=None,
                text=outcome.visible_text,
                structured=extract_structured(outcome.html),
                screenshot_png=outcome.screenshot_png,
                locale=detect_locale_markers(outcome.html, outcome.visible_text, outcome.headers),
                collection_country=ctx.collection_country,
            ),
        )
        status, detail = _status_for(outcome.status, outcome.html)
        results.append(CaptureResult(spec.key, outcome.label, method, status, detail, ref))
    return results
```

- [ ] **Step 4: The CLI.** `src/mihenk/cli.py`:

```text
mihenk capture URL [--key KEY] [--method fetch|render|render_interact]
                    [--state LABEL] [--state LABEL=CLICK_TEXT] ...
                    [--ignore-robots] [--country CC] [--data-dir DIR]
```

  `--key` defaults to a slug made from the URL's host and path (lowercase, `[a-z0-9-]`, at most 64 characters). `--state LABEL` adds a state with no actions; `--state LABEL=TEXT` adds a state that clicks the exact text `TEXT`. With no `--state`, the recipe has one state `default`. `--country` defaults to the operating system's region (`locale.getlocale()[0]` region part, upper case), else `"ZZ"` (unknown). It creates a run id, starts Playwright only for render methods (it calls `start_playwright_env(data_dir)`, then `sync_playwright()` and `launch_browser(pw, allow_downloaded=True)`; Task 1.10 adds `start_playwright_env`, so until then the CLI calls `launch_browser(pw)`), runs `capture_page`, and prints one line per state: label, status, detail and snapshot folder. Exit code: 0 if every state is `ok`, 1 otherwise. `launcher.main` passes `argv` to `cli.main` when its first item is `capture` or `install-browser`.

  `tests/integration/test_cli.py` runs `cli.main(["capture", site.url("/static-table"), "--data-dir", str(tmp_path)])`, expects exit 0 and a snapshot folder under `tmp_path/snapshots/`; and `--state monthly=Monthly` against `billing-toggle` with `--method render_interact` (browser-marked). The render case starts its own Playwright session, so it runs the CLI in a subprocess, `subprocess.run([sys.executable, "-m", "mihenk", "capture", ...], timeout=120)`, never `cli.main` in the test process (Task 0.6's one-session rule).

- [ ] **Step 5: Run everything.** `uv run pytest -v && uv run mypy && uv run ruff check . && uv run python tools/check_price_arithmetic.py && uv run python tools/check_licenses.py` → all pass. **Commit:** `git add -A && git commit -m "Capture orchestration, bot-wall detection and the capture CLI"`

### Task 1.10: Playwright's Chromium, only with consent

**Files:**
- Modify: `src/mihenk/capture/browser.py`, `src/mihenk/cli.py`, `src/mihenk/app/launcher.py` (also hand `_playwright-install` to `cli.main`)
- Test: `tests/unit/test_browser_install.py`

**Interfaces:** Produces `browsers_dir(data_dir: Path) -> Path` (`data_dir / "browsers"`), `has_downloaded_chromium(data_dir: Path) -> bool` (any `chromium-*` folder inside), `start_playwright_env(data_dir: Path) -> None` (sets `PLAYWRIGHT_BROWSERS_PATH` to `browsers_dir`; must run before `sync_playwright()` starts), `install_command(data_dir: Path, frozen: bool) -> tuple[list[str], dict[str, str]]`, `install_chromium(data_dir: Path) -> int`; CLI `mihenk install-browser [--yes]`; hidden CLI entry `mihenk _playwright-install` that calls Playwright's own command-line entry.

- [ ] **Step 1: Confirm Playwright's entry point.** Check that the installed `playwright/__main__.py` defines `main()` that runs the driver with `sys.argv[1:]`. If it does not, record the alternative used in `docs/decisions/NNNN-browser-download.md`.
- [ ] **Step 2: Write the failing tests.** `tests/unit/test_browser_install.py`:

```python
import sys
from pathlib import Path

from mihenk.capture.browser import browsers_dir, has_downloaded_chromium, install_command


def test_install_command_when_running_from_source(tmp_path: Path) -> None:
    command, env = install_command(tmp_path, frozen=False)
    assert command == [
        sys.executable,
        "-m",
        "mihenk",
        "_playwright-install",
        "install",
        "chromium",
        "--no-shell",
    ]
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == str(browsers_dir(tmp_path))


def test_install_command_when_frozen(tmp_path: Path) -> None:
    command, _ = install_command(tmp_path, frozen=True)
    assert command == [sys.executable, "_playwright-install", "install", "chromium", "--no-shell"]


def test_detects_a_downloaded_chromium(tmp_path: Path) -> None:
    assert not has_downloaded_chromium(tmp_path)
    (browsers_dir(tmp_path) / "chromium-1243").mkdir(parents=True)
    assert has_downloaded_chromium(tmp_path)
```

- [ ] **Step 3: Implement.** In `browser.py` add the functions above; `install_chromium` runs `subprocess.run(command, env={**os.environ, **env}, check=False)` and returns its exit code. `--no-shell` skips the separate headless shell (about 100 MB less, §22); the downloaded browser is then launched with `channel="chromium"`, which `launch_browser(..., allow_downloaded=True)` already tries last. In `cli.py`, `install-browser` prints `Download Playwright's Chromium (about 200 MB) into <folder>? It is only needed if Chrome and Edge are not installed. [y/N]` and runs only on `y` or with `--yes`. `_playwright-install` sets `sys.argv = ["playwright", *rest]` and calls Playwright's `main()`. In `launcher.py`, add `_playwright-install` to the first-argument names that `main` hands to `cli.main` (the frozen app has no `-m mihenk`, so this is how `install_command(..., frozen=True)` reaches it). In `cli.py`, the `capture` command now calls `start_playwright_env(data_dir)` before `sync_playwright()` and launches with `launch_browser(pw, allow_downloaded=True)`, so a downloaded Chromium is found.
- [ ] **Step 4: Run** the unit tests → PASS. The real download (about 200 MB) is not run in CI. Aydin may run `uv run mihenk install-browser` by hand on a machine without Chrome to confirm it; that is optional for stage 1.
- [ ] **Step 5: Commit.** `git add -A && git commit -m "Consent-based Chromium download as the last browser option"`

### Stage 1 done

- [ ] All checks green on Windows and macOS in CI.
- [ ] Every trap page is captured by the methods its `expect.json` names, with snapshots, hashes and locale markers.
- [ ] Aydin ran `uv run mihenk capture <a real pricing page of Aydin's choosing>` (and, if the page has a billing toggle, a `render_interact` run with `--state`) and looked at the snapshot folder. Its result goes into `docs/decisions/NNNN-first-live-capture.md`: the URL, the method, what the text and screenshot showed. No vendor page is committed.
- [ ] `CHANGELOG.md` updated; ask Aydin whether to open the stage-1 pull request.

---

## Roadmap: stages 2 to 6

Each stage gets its own plan, written after the previous stage lands, from what it taught. Done-when lines come from the design §21.

| Stage | Contents | Done when |
|---|---|---|
| 2. Extraction and checks | `core/fields.py` (core field definitions, value states, money parsing without arithmetic; the arithmetic lint reads its field list from here); `llm/` with the OpenAI provider (`gpt-6-luna`, Responses API, strict schema, `reasoning={"effort": "low"}`, `store=False`, refusal detection) and the Claude provider (`claude-opus-5-5`, `messages.parse`, refusal fallback on, answering model recorded); API keys in `keyring` (Windows persistence set to local machine); `verify/` with the quote check (§8.6), cross-check (§8.7) and sanity checks (§8.8); extraction answers (value, quote, position) added to every trap page; LLM answers recorded once for offline tests, live re-check only when Aydin starts it | Recorded LLM answers pass the quote check and cross-check on every trap page; zero ungrounded values would reach a view |
| 3. Store and Review | SQLite `STRICT` schema with append-only triggers and migrations; one writer connection; runs, captures, extractions, plans, values, flags, reviews; the effective-value rule (§7.4); the run worker thread that owns Playwright; run progress as server-sent events read with `fetch` (the token header must travel); the Review screen | A run's values are stored append-only and reviewed in the Review screen |
| 4. Market views and customisation | Plans table (TanStack Table), Features matrix and feature extraction (§8.9), classification into the user's taxonomy (§8.10), custom fields, the Settings screen (provider, key, model, effort, conduct, country, data folder) | The market views work on trap pages and on one live market Aydin picks |
| 5. Changes, export, helper | Changes between runs (§12), CSV, JSON and Excel export (§13), the add-a-brand helper (§8.4), workspace YAML import and export, the update check | Two runs compared; the Excel export matches the JSON |
| 6. Public beta | Privacy notice, Licences screen, download page text (including the Smart App Control note), live canary script, release workflow. Each release needs Aydin's go | Unsigned installers and the wheel on GitHub Releases |

## Rules for every stage

- Test first: the failing test, then the code, then the passing test (as the tasks above show).
- All checks in `CLAUDE.md` pass before a stage is called done; a check that did not run is reported as not run.
- One review per task. Fix Critical and Important findings once, without a second review round; collect minor findings and fix them at the end of the stage.
- Each stage ends with a short record, `docs/planning/<date>-stage-<n>-record.md`: rulings made during the stage and deferred findings, plus the changelog entry.
- No live vendor visit and no paid LLM call except in a step Aydin starts.
