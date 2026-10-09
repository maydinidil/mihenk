"""Builds the React screens into the package and adds the third-party notices to the wheel
(design §17, §18)."""

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
        if version == "editable":
            return  # uv sync installs the project this way and never needs the screens or notices
        if os.environ.get("MIHENK_SKIP_WEB_BUILD") != "1":
            self._build_screens()
        notices = Path(self.root) / "THIRD_PARTY_NOTICES.txt"
        if not notices.is_file():
            raise RuntimeError("run tools/gen_notices.py before building a wheel")
        build_data["force_include"][str(notices)] = "mihenk/THIRD_PARTY_NOTICES.txt"

    def _build_screens(self) -> None:
        npm = shutil.which("npm")
        if npm is None:
            raise RuntimeError("npm is needed to build the mihenk screens; install Node.js 24")
        web = Path(self.root) / "web"
        subprocess.run([npm, "ci"], cwd=web, check=True)
        subprocess.run([npm, "run", "build"], cwd=web, check=True)
        index = Path(self.root) / "src" / "mihenk" / "web_dist" / "index.html"
        if not index.is_file():
            raise RuntimeError("the screens build produced no index.html")
