# 0004: Installing with uv from a wheel URL

Date: 2026-10-09. Status: Decided. `uv tool install <wheel URL>` works; the README can offer it.

## The question

Can someone who already has `uv` install mihenk straight from the URL of a release wheel, with no
installer and no clone (§17)?

## What was run (Windows 11 x64, uv 0.11.13)

The wheel was served from this machine, so nothing came from GitHub. Both tool folders pointed
into a fresh temporary folder, so nothing landed in Aydin's own uv tools.

```sh
uv run python tools/gen_notices.py
uv build --wheel
uv run python -m http.server 8765 --bind 127.0.0.1 --directory dist

# in another shell
export UV_TOOL_DIR=<temp>/tools UV_TOOL_BIN_DIR=<temp>/bin
uv tool install http://127.0.0.1:8765/mihenk-0.0.1-py3-none-any.whl
<temp>/bin/mihenk --smoke --data-dir <temp>/data
uv tool uninstall mihenk
```

| Step | Result |
|---|---|
| `uv build --wheel` | Pass: `dist/mihenk-0.0.1-py3-none-any.whl` |
| `uv tool install` from the URL | Pass. uv accepted the URL directly, downloaded the dependencies from PyPI and installed one executable, `mihenk` |
| `mihenk --smoke` from the tool's bin folder | Exit code 0 in 4.8 seconds; the log shows the server start |
| `uv tool uninstall mihenk` | Pass |
| Clean-up | Server stopped, temporary folder deleted, `uv tool list` shows no mihenk |

The smoke ran with its data folder inside the temporary folder, outside the real user profile.

## Decision

The README offers, for people who use uv:

```sh
uv tool install https://github.com/maydinidil/mihenk/releases/download/v<version>/mihenk-<version>-py3-none-any.whl
```

No fallback is needed: uv took the URL as it is. If a future uv refuses a URL, the fallback is to
download the wheel first and run `uv tool install ./mihenk-<version>-py3-none-any.whl`.

## Not checked here

- A URL on GitHub Releases, which redirects to another host. The local server did not redirect.
  The first release checks it once.
- macOS. The wheel is pure Python and the same command applies; the first macOS CI run or release
  checks it.
