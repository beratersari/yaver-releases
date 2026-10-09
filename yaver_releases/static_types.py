"""Content types for files under /static.

Windows often has no ``.woff2`` mapping, and some machines map ``.js`` to
``text/plain``. Starlette then guesses ``application/octet-stream`` or
``text/plain``. The site sends ``X-Content-Type-Options: nosniff``, so the
browser refuses the file. A refused ``theme.js`` leaves the night/light
switch with no click handler. A refused font is the MIME error in the
network panel.
"""

from __future__ import annotations

from pathlib import Path

_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".gif": "image/gif",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def media_type_for(path: str) -> str | None:
    """Return the browser type for a static file, ignoring the OS map."""
    return _TYPES.get(Path(path).suffix.lower())
