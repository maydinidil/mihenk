# Codex findings

Reviewer findings on mihenk's pull requests, each with a verdict and a status. Newest review
first. IDs are stable and never reused. Paths are relative to the repository root.

| Status | Meaning |
|---|---|
| `OPEN` | Verdict reached, not fixed yet |
| `FIXED <date>` | Reproduced, fixed, proven by a test |
| `REFUTED <date>` | The code does not do what was claimed |
| `WON'T FIX <date>` | Real, and deliberately left, with the reason |

## PR #2, Stage 1: capturing pages (Codex review 2026-10-12, commit 462e2c9)

### F1: The frozen app is never checked to run Playwright

**P1 · `src/mihenk/cli.py:226` · Verdict: CONFIRMED, with a correction · Status: OPEN**

Codex says the Playwright driver (`node`, `cli.js`) is not in the frozen app because
`packaging/mihenk.spec` collects only the screens and the notices, so every browser-backed command
(`capture` with a render method, `install-browser`) would fail in a release.

Correction: the driver is bundled. Playwright ships its own PyInstaller hook
(`playwright/_impl/__pyinstaller/hook-playwright.sync_api.py`, `collect_data_files("playwright")`),
which PyInstaller runs without the spec naming it; the build logs of 2026-10-12 show it processed
on Windows and macOS, and the stage 1 record notes the driver in the frozen app. What is true: no
build step runs a Playwright command from the frozen app. The release check (`--smoke`) only opens
the window, so a bundle whose driver cannot start would still pass CI. The severity is Codex's;
until stage 3 runs captures inside the app, only the command line reaches this path.

**Fix direction:** add a build step on both systems that runs the frozen app with
`_playwright-install --version` (it asks the local driver for its version, offline) and fails on a
non-zero exit; the Windows step reads the exit code, since the windowed build has no console.

### F2: A fetch can run well past its deadline

**P2 · `src/mihenk/capture/fetch.py:229` · Verdict: CONFIRMED, with a correction · Status: OPEN**

Codex says the whole-fetch deadline (90 s for a page, 30 s for robots.txt) is checked only between
operations, so a connect or read that starts just before it can still use httpx2's full 30 second
per-operation timeout.

Correction: decision 0006 already states the overrun ("a fetch ends within `deadline_s` plus about
one `timeout_s`"), so it is not silent. The stated bound is too low, though: the deadline is checked
before `client.send`, and one send can spend a connect, a write and a header read, each up to
`timeout_s`, so a robots.txt fetch could take about 30 + 90 seconds instead of 30 + 30.

**Fix direction:** give each request a timeout of `min(timeout_s, time left before the deadline)`
(httpx2 takes a per-request timeout when the request is built), for the first request and each
redirect hop; a test with a server that stalls the headers just before the deadline; correct the
bound in decision 0006.

### F3: A user name and password in the page address are written into the snapshot

**P2 · `src/mihenk/capture/snapshot.py:224` · Verdict: CONFIRMED · Status: OPEN**

`is_http_url` (`src/mihenk/capture/run.py:80`) accepts an address with a user name and password
(`https://user:password@example.com/pricing`), and `write_snapshot` records `url` and `final_url`
as given, so the password is kept in `meta.json` for good (snapshots are never modified).
robots.txt and pacing already drop the user name and password (`robots_url`, `host_key`).

**Fix direction (a choice for Aydin):** either redact the user name and password from `url` and
`final_url` before they are recorded (captures of such pages keep working; the credentials are
still sent to the site, as typed), or refuse such addresses at the door with a clear message.
Recommended: redact, the narrower change.

## PR #1, Stage 0: the foundation (Codex review 2026-10-12, commit cc8e3de)

No findings.
