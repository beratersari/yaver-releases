"""Platform ids shared with the Yaver update client.

Keep these ids in sync with ``src/self_update.py`` in the Yaver repo.
"""

from __future__ import annotations

import re
import stat
from pathlib import Path

PLATFORMS: dict[str, str] = {
    "windows": "Windows",
    "ubuntu-18.04": "Ubuntu 18.04",
    "ubuntu-20.04": "Ubuntu 20.04",
    "ubuntu-22.04": "Ubuntu 22.04",
    "ubuntu-24.04": "Ubuntu 24.04",
}

_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.]+)?$")
_MAX_MEMBERS = 200_000
_MAX_UNCOMPRESSED = 16 * 1024 * 1024 * 1024


class PackageError(ValueError):
    """The upload is not a publishable Yaver zip."""


def require_version(value: str) -> str:
    text = (value or "").strip()
    if not _VERSION.fullmatch(text):
        raise PackageError("Version must look like 0.9.72.")
    return text


def safe_filename(name: str) -> str:
    base = Path(name or "").name.replace("\\", "/").split("/")[-1]
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    if not cleaned.lower().endswith(".zip"):
        raise PackageError("Upload a .zip file.")
    return cleaned[:180]


def _member_parts(name: str) -> list[str]:
    text = (name or "").replace("\\", "/").strip()
    if not text:
        return []
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise PackageError("The zip contains an absolute path.")
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise PackageError("The zip contains a parent path.")
    return parts


def _is_link(info: object) -> bool:
    mode = (int(getattr(info, "external_attr", 0)) >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def inspect_zip(path: Path) -> str:
    """Return ``frozen``, ``source``, or ``unknown``. Reject unsafe zips."""
    import zipfile

    if not zipfile.is_zipfile(path):
        raise PackageError("The file is not a zip.")
    names: list[str] = []
    total = 0
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > _MAX_MEMBERS:
            raise PackageError("The zip has too many files.")
        for info in infos:
            if _is_link(info):
                raise PackageError("The zip contains a symlink.")
            parts = _member_parts(info.filename)
            total += max(0, int(info.file_size))
            if total > _MAX_UNCOMPRESSED:
                raise PackageError("The zip expands to more than 16 GB.")
            if parts:
                names.append("/".join(parts))
    return classify_members(names)


def classify_members(names: list[str]) -> str:
    """Classify a zip listing. A single wrapping folder is unwrapped."""
    cleaned: list[str] = []
    for name in names:
        parts = _member_parts(name)
        if parts:
            cleaned.append("/".join(parts))
    prefixes = {item.split("/", 1)[0] for item in cleaned if "/" in item}
    root_files = [item for item in cleaned if "/" not in item]
    relative = cleaned
    if len(prefixes) == 1 and not root_files:
        prefix = next(iter(prefixes)) + "/"
        relative = [item[len(prefix):] for item in cleaned if item.startswith(prefix)]
    joined = set(relative)
    has_internal = any(item == "_internal" or item.startswith("_internal/") for item in joined)
    has_exe = "yaver.exe" in joined or "yaver" in joined
    has_source = "src/daemon.py" in joined and "VERSION" in joined
    if has_exe and has_internal:
        return "frozen"
    if has_source:
        return "source"
    return "unknown"
