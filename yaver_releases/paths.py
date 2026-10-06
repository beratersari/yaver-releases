"""Where the running site keeps its files.

A source run uses the working directory. A frozen executable uses the
folder that contains the executable, so a double-click still finds the
``.env`` and the published zips that sit next to it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def install_dir() -> Path:
    if frozen():
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def data_dir(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    raw = (os.environ.get("YAVER_RELEASE_DATA") or "").strip()
    base = install_dir()
    if not raw:
        return base / "data"
    chosen = Path(raw)
    if chosen.is_absolute():
        return chosen
    return base / chosen
