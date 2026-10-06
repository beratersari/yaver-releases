"""PyInstaller entry: same process as ``python -m yaver_releases``."""

from __future__ import annotations

import multiprocessing

multiprocessing.freeze_support()

from yaver_releases.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
