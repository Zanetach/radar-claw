from __future__ import annotations

import os
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_BIN_DIR = PROJECT_ROOT / "tools" / "beeclaw-bin"


def resolve_cli(command: str) -> str | None:
    """Resolve a Beeclaw CLI command from PATH or the project-bundled bin dir."""
    override_name = f"BEECLAW_{command.upper().replace('-', '_')}_BIN"
    override = os.getenv(override_name)
    if override:
        return override

    path = shutil.which(command)
    if path:
        return path

    bundled = PROJECT_BIN_DIR / command
    if bundled.exists() and os.access(bundled, os.X_OK):
        return str(bundled)
    return None


def cli_health(command: str) -> dict[str, object]:
    path = resolve_cli(command)
    return {
        "installed": bool(path),
        "path": path,
        "source": "project" if path and str(path).startswith(str(PROJECT_BIN_DIR)) else "system" if path else None,
    }
