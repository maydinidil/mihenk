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
