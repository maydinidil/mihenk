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
