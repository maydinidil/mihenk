# mihenk

mihenk is a desktop app that tracks competitors' **pricing and packaging**: plans, prices, billing
terms, limits and features of SaaS-style products. You point it at vendors' pricing pages. It
captures each page, uses an LLM through your own API key to extract the plans into structured
data, checks every extracted number against a verbatim quote from the page, and keeps a dated
history you can review, compare and export.

The name is Turkish for touchstone (*mihenk taşı*), the stone used to test gold. In Turkish it
also means a benchmark. The app tests every price against its source.

## State

**Stage 0: not usable yet.** The foundation is built: a local server that only this machine can
reach, the app window with an empty set of screens, the browser driver, the repository checks,
the packaging scripts and CI. Capturing pricing pages is stage 1. There is nothing to install
today: no release has been published yet.

| Where | What |
|---|---|
| `docs/superpowers/specs/2026-10-08-mihenk-design.md` | The approved design |
| `docs/superpowers/plans/2026-10-08-mihenk-stages-0-1.md` | The plan for stages 0 and 1 |
| `docs/decisions/` | Decisions taken during the build, one file each |
| `CHANGELOG.md` | What changed, release by release |

## Licence

mihenk is **source-available**, not open source. It is licensed under the
[PolyForm Noncommercial License 1.0.0](LICENSE).

| Question | Answer |
|---|---|
| Can I use it for study, research, a hobby, a school, a charity or a public body? | Yes, any non-commercial purpose |
| Can a company use it in its business? | Not under this licence. A commercial licence is needed |
| Can I try it at work first? | Yes, for up to 30 days from first use, to decide whether to keep using it or ask for a commercial licence. See [`EVALUATION.md`](EVALUATION.md) |
| Do I have to credit the author? | Yes. Anyone who passes mihenk on must pass on the lines in [`NOTICE`](NOTICE) |
| Where do I ask for a commercial licence? | Through [github.com/maydinidil](https://github.com/maydinidil) |

The full terms are in [`LICENSE`](LICENSE). This summary is a convenience and does not replace them.

## Checks

These are the checks the project uses. Run them from the repository root; CI runs the same
commands on Windows and macOS.

| Check | Command |
|---|---|
| Python format and lint | `uv run ruff format --check . && uv run ruff check .` |
| Python types | `uv run mypy` |
| Python tests | `uv run pytest` |
| Screens | `cd web && npm run lint && npm run typecheck && npm test && npm run build` |
| API types up to date | `uv run python tools/dump_openapi.py && (cd web && npm run gen:api) && git diff --exit-code web/openapi.json web/src/api/schema.ts` |
| Licences | `uv run python tools/check_licenses.py` |
| No arithmetic on prices | `uv run python tools/check_price_arithmetic.py` |

To set up the Python environment, install [uv](https://docs.astral.sh/uv/) and run `uv sync`. It
fetches Python 3.13 and the locked dependencies.
