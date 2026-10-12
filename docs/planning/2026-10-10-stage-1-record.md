# Stage 1 record

Date: 2026-10-10. Branch: `stage-1`. Plan: `docs/superpowers/plans/2026-10-08-mihenk-stages-0-1.md`.

Stage 1 captures pages. It adds the trap pages the tests run against, the robots.txt check, pacing,
fetching, page text and embedded data, locale signals, snapshot folders, rendering in the installed
browser, the `mihenk capture` command and an optional Chromium download. Each task was built by one
agent and reviewed once by another. Important findings were fixed once; smaller ones were collected
and fixed together at the end of the stage.

## State at the end of the stage

| Item | State |
|---|---|
| Tasks 1.1 to 1.10 | Done on this machine |
| Stage-end small fixes | Two batches, 57 items: 52 from stage 1's task reviews, 1 flaky timing test and 4 carried from stage 0's final review. Items not done are listed under Carried forward |
| Tests | 1508 Python tests pass with the browser tests required; ruff, mypy, the price lint and the licence check are clean |
| Every trap page captured by the methods its `expect.json` names | Passes (`test_every_trap_page_by_its_methods`) |
| Final review (seams between tasks) | Two Important findings and seven smaller ones, all fixed in one round (below). The other nine seams held |
| CI on Windows and macOS | Not run yet; waits for the first push |
| A live capture of a real pricing page | Waits for Aydin |
| GitHub repository | `maydinidil/mihenk` exists, public and empty; nothing pushed |

## Rulings made during the stage

| Ruling | Why |
|---|---|
| robots.txt is checked before every request, redirect hops included, and its own requests are paced like any other | §8.2 applies per site, and a redirect can lead to another site |
| One robots.txt fetch per site per run; the site is spelled one way (lower-case scheme, IDNA host, no default port, no user name or password) | Spelling variants would cost extra fetches, and a typed password must never travel to robots.txt |
| robots.txt that is unreachable, unreadable, or answers 401, 403 or 5xx means disallow-all; 429 means disallowed for this run; other 4xx means allowed | Fail closed except where RFC 9309 says a missing file allows |
| Every fetch has a whole-request deadline (90 s for a page, 30 s for robots.txt); redirect bodies are never read; at most 5 hops | A server trickling one byte at a time would otherwise never time out |
| Charset labels are read the way browsers read them (iso-8859-1 and us-ascii as windows-1252, iso-8859-9 as windows-1254) | Real pages labelled iso-8859-1 contain the euro sign and curly quotes |
| Snapshot folder names refuse Windows reserved names (`con`, `nul`, `com1`...), and a snapshot path longer than 259 characters is refused before anything is written | Windows cannot create those names, and the default Windows path limit would fail halfway |
| `meta.json` lists a SHA-256 for every file in the snapshot; JSON files are written as UTF-8 with LF line endings | Snapshots are never modified, so missing hashes could never be added later; the same bytes on Windows and macOS give the same hashes |
| Page text keeps the body when a page never closes its `<head>`, and is built without recursion | The HTML parser nests such a body inside the head; deeply nested real pages would exceed Python's recursion limit |
| Embedded JSON with NaN, Infinity, an unpaired surrogate, a number too long or nesting too deep is kept as raw text with a problem label | One hostile block must not stop a capture or write invalid JSON |
| Negated VAT wording ("KDV dahil değildir", "niet inclusief btw", "nicht inkl. MwSt.", "not incl. VAT") is never read as VAT included | Reading it as included gives the opposite price meaning |
| "+ IVA" is both Spanish and Italian; VAT phrases are checked by containment, and the page language decides later | The overlap is real and cannot be removed without losing one language |
| Bot-wall markers that also appear on ordinary pages (Cloudflare's challenge platform, Imperva's resource, Cloudflare's `cf-chl-` widget ids) count only with a 403, 429 or 503 answer | Cloudflare's Turnstile widget and script appear on many normal pricing pages |
| Rendering uses a fresh browser context per capture and a fresh page per state, with service workers blocked, downloads off and dialogs dismissed | Nothing carries over between captures, and a page cannot stall the capture with an alert |
| Waits on a rendered page are bounded: quiet network for 500 ms (capped), a 2 s scroll, and a timeout on reading the HTML | A page that never goes quiet, or a script that spins forever, must not freeze the capture |
| The status recorded for a rendered state comes from the last main-frame navigation | A page that reloads from 403 to 200, or a click that navigates to a 404, would otherwise be recorded wrongly |
| Lone surrogates in rendered pages are replaced with U+FFFD | They cannot be written as UTF-8 |
| The default `--country` comes from the Windows user locale's region (`GetUserDefaultLocaleName`), else `ZZ` | Python's own locale name on Windows reads "English_Netherlands" |
| One http client per run, closed at the end | Cookies must never cross brands or runs (§8.3) |
| Chromium is downloaded only after an explicit yes (`mihenk install-browser`); `mihenk capture` never downloads | It is about 200 MB and only needed without Chrome or Edge |
| Tests clear proxy settings for themselves; the app keeps reading them | Tests must stay on 127.0.0.1; users behind a company proxy need it |
| Host names are spelled the way the HTTP client and Chrome spell them (IDNA 2008), for pacing and robots.txt alike | Python's own codec turns `faß.de` into `fass.de`, another domain, so robots.txt was read from the wrong site |
| The browsers the tests launch are confined to 127.0.0.1 (`MIHENK_BROWSER_LOOPBACK_ONLY`: a host resolver that finds nothing else, and a proxy that goes nowhere) | The final review found branded Chrome connecting to Google's own services during the test run; Playwright's switches do not stop them |
| robots.txt is fetched with its own HTTP client | A cookie robots.txt sets must not reach the page request |
| A snapshot path that would be too long is refused before any request | A run that cannot be saved should not contact the site at all |

## Carried forward

| Item | Where it goes |
|---|---|
| A trap page whose prices are only in the Next.js data blob | Stage 2, with extraction |
| The page language has to choose among VAT phrases ("+ IVA" is Spanish and Italian, "HT" reads as French, "BSO + KDV" as Turkish) | Stage 2 |
| "TL" beside a number is not always Turkish lira; "Kr 99" and "199 Kr" are not marked | Stage 2 |
| A snapshot write failure produces no result and loses earlier states' results; a browser dying mid-loop marks already-rendered states as browser unavailable | Stage 2 |
| A robots.txt refusal does not name the rule (Protego has no way to report it) | Stage 3, the Review screen |
| Stale `.tmp-` folders from an interrupted write are not swept | Stage 3: readers skip names starting `.tmp-` |
| The snapshot path-length check should run when a page is added, not after its first fetch | Stage 3, pages and recipes |
| The render route checks robots.txt for the final URL after rendering all states | Stage 3's capture worker may check after the first state |
| A rendered page's own resources (styles, scripts, data requests, frames) get no robots decision or pacing | Design note: §8.2's rules govern the pages mihenk navigates to; the browser loads a page's resources as any browser does |
| Every settle step takes at least 1 s | Accepted: correctness over speed, capped |
| "not incl. VAT" gives no phrase rather than an excl one | Accepted: a missing marker is the safer failure |
| The windowed app has no console, so `install-browser` cannot ask there | The screens' consent step, in a later stage |
| The frozen build does not yet include Playwright's driver (`node.exe`, `cli.js`) | Check at the next frozen build |
| A downloaded Chromium found through `channel="chromium"` | Unverified here (Chrome is installed); Aydin's optional hand run |

## Waiting for Aydin

| Item | Note |
|---|---|
| Chrome's own traffic during real captures: branded Chrome contacts Google for its own services while mihenk drives it, which the promise "no network call except tracked pages, the chosen provider and the update check" does not allow for | A decision before stage 3, where captures run inside the app |
| A live capture of a real pricing page | `uv run mihenk capture <URL>`; for a page with a billing toggle also `--method render_interact --state ...`. The result goes into a decision record; no vendor page is committed |
| Push `stage-1` (and stage 0's branches) | CI on Windows and macOS runs after the push |
| Open the stage-1 pull request | After CI is green |
| Stage 0's open items | The hand checks (the window opens and closing it ends the app; `--smoke` with the default data folder) and the private record commit. Settled on 2026-10-12: the two missing licence texts are kept in `tools/licence_texts/`, and decision 0005 is accepted (no Microsoft Store) |
| Optional: `uv run mihenk install-browser` on a machine without Chrome or Edge | Confirms the download path |
