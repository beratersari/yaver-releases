"""Run from the install folder so .env next to the executable is found."""

from __future__ import annotations

import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    install = Path(sys.executable).resolve().parent
    try:
        os.chdir(install)
    except OSError:
        pass
