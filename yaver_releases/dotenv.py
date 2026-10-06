"""Load a local .env without extra dependencies. Existing variables win."""

from __future__ import annotations

import os
from pathlib import Path

from yaver_releases import paths


def load_dotenv(path: Path | None = None) -> None:
    dest = path if path is not None else paths.install_dir() / ".env"
    if not dest.is_file():
        return
    try:
        text = dest.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")
