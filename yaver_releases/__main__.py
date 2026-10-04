"""python -m yaver_releases"""

from __future__ import annotations

import os

import uvicorn

from yaver_releases.app import create_app
from yaver_releases.dotenv import load_dotenv


def main() -> None:
    load_dotenv()
    host = (os.environ.get("YAVER_RELEASE_HOST") or "0.0.0.0").strip() or "0.0.0.0"
    raw_port = (os.environ.get("YAVER_RELEASE_PORT") or "8090").strip()
    try:
        port = int(raw_port)
    except ValueError:
        port = 8090
    if port < 1 or port > 65535:
        port = 8090
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
