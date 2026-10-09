"""Writes web/openapi.json from the FastAPI app, for openapi-typescript (design §5)."""

import json
from pathlib import Path

from mihenk.api.security import GuardConfig
from mihenk.api.server import create_app


def main() -> None:
    # The schema needs no real token; GuardConfig only refuses tokens shorter than 32 characters.
    app = create_app(GuardConfig(port=1, token="x" * 32), web_dist=None)
    out = Path(__file__).resolve().parent.parent / "web" / "openapi.json"
    # newline="\n": the repository keeps LF in every working copy, Windows included.
    text = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    out.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
