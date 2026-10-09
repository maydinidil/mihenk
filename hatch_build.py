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
