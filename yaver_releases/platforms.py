"""Platform ids shared with the Yaver update client.

Keep these ids in sync with ``src/self_update.py`` in the Yaver repo.
"""

from __future__ import annotations

import os
import re
import stat
import zipfile
from pathlib import Path

PLATFORMS: dict[str, str] = {
    "windows": "Windows",
    "ubuntu-18.04": "Ubuntu 18.04",
    "ubuntu-20.04": "Ubuntu 20.04",
    "ubuntu-22.04": "Ubuntu 22.04",
    "ubuntu-24.04": "Ubuntu 24.04",
}

# Office downloads for the CLIs. These ids are not Yaver update targets.
# ``yaver update`` only asks for a platform in ``PLATFORMS``.
DEPENDENCIES: dict[str, str] = {
    "opencode-windows": "OpenCode for Windows",
    "opencode-linux": "OpenCode for Linux",
    "claude-windows": "Claude Code for Windows",
    "claude-linux": "Claude Code for Linux",
    "codex-windows": "Codex for Windows",
    "codex-linux": "Codex for Linux",
}


def package_label(platform: str) -> str:
    if platform in PLATFORMS:
        return PLATFORMS[platform]
    return DEPENDENCIES.get(platform, platform)

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


def version_from_zip(path: Path) -> str | None:
    """Read ``VERSION`` at the zip root.

    Returns ``None`` when that file is absent. A present file must be a
    short version string. Call this after a wrapping folder is removed.
    """
    if not zipfile.is_zipfile(path):
        raise PackageError("The file is not a zip.")
    chosen: zipfile.ZipInfo | None = None
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if _is_link(info) or _is_dir_entry(info):
                continue
            if _member_parts(info.filename) != ["VERSION"]:
                continue
            chosen = info
            break
        if chosen is None:
            return None
        if int(chosen.file_size) > 200:
            raise PackageError("The VERSION file is not a version.")
        raw = archive.read(chosen)
    try:
        text = raw.decode("utf-8-sig").strip()
    except UnicodeError as exc:
        raise PackageError("The VERSION file is not a version.") from exc
    line = text.splitlines()[0].strip() if text else ""
    if not line:
        raise PackageError("The VERSION file is empty.")
    return require_version(line)


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


def _is_dir_entry(info: zipfile.ZipInfo) -> bool:
    name = str(info.filename).replace("\\", "/")
    return info.is_dir() or name.endswith("/")


def _single_folder_prefix(names: list[str]) -> str | None:
    """Return ``Folder/`` when every file lives under that one directory."""
    if not names:
        return None
    tops = {name.split("/", 1)[0] for name in names}
    if len(tops) != 1 or any("/" not in name for name in names):
        return None
    return next(iter(tops)) + "/"


def flatten_wrapper(path: Path) -> bool:
    """Drop one wrapping folder so a download lists the package files.

    A zip that already has ``yaver.exe`` or ``VERSION`` at the top is left
    unchanged. Unsafe paths are rejected before anything is rewritten.
    """
    if not zipfile.is_zipfile(path):
        raise PackageError("The file is not a zip.")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > _MAX_MEMBERS:
            raise PackageError("The zip has too many files.")
        file_names: list[str] = []
        total = 0
        for info in infos:
            if _is_link(info):
                raise PackageError("The zip contains a symlink.")
            if _is_dir_entry(info):
                continue
            parts = _member_parts(info.filename)
            total += max(0, int(info.file_size))
            if total > _MAX_UNCOMPRESSED:
                raise PackageError("The zip expands to more than 16 GB.")
            if parts:
                file_names.append("/".join(parts))
        prefix = _single_folder_prefix(file_names)
        if prefix is None:
            return False
        expanded = 0
        tmp = path.with_name(path.name + ".flat")
        try:
            with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as out:
                for info in infos:
                    if _is_dir_entry(info):
                        continue
                    parts = _member_parts(info.filename)
                    if not parts:
                        continue
                    rel = "/".join(parts)
                    if not rel.startswith(prefix):
                        raise PackageError("The zip folder could not be removed.")
                    inner = rel[len(prefix):]
                    if not inner or any(part == ".." for part in inner.split("/")):
                        raise PackageError("The zip folder could not be removed.")
                    stored = zipfile.ZipInfo(filename=inner, date_time=info.date_time)
                    stored.compress_type = zipfile.ZIP_DEFLATED
                    stored.external_attr = info.external_attr
                    stored.create_system = info.create_system
                    with archive.open(info, "r") as src, out.open(stored, "w") as dest:
                        while True:
                            block = src.read(1024 * 1024)
                            if not block:
                                break
                            expanded += len(block)
                            if expanded > _MAX_UNCOMPRESSED:
                                raise PackageError("The zip expands to more than 16 GB.")
                            dest.write(block)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise PackageError("The zip folder could not be removed.") from exc
    return True


def inspect_zip(path: Path) -> str:
    """Return ``frozen``, ``source``, ``cli``, or ``unknown``. Reject unsafe zips."""
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
    if _is_cli(joined):
        return "cli"
    return "unknown"


def _is_cli(names: set[str]) -> bool:
    """One tool zip: its installer plus ``tool/tool`` or ``tool/tool.exe``."""
    for tool in ("opencode", "claude", "codex"):
        binary = f"{tool}/{tool}" in names or f"{tool}/{tool}.exe" in names
        installer = f"install-{tool}.sh" in names or f"install-{tool}.bat" in names
        if binary and installer:
            return True
    return False
