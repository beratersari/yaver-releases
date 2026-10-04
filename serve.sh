#!/bin/sh
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then
  exec .venv/bin/python -m yaver_releases
fi
exec python3 -m yaver_releases
