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

# Office downloads for the CLIs. These ids are not Yaver package targets.
# update.bat and update.sh only ask for a platform in ``PLATFORMS``.
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


def updater_name(platform: str) -> str | None:
    """Script file a frozen zip for this platform must contain."""
    if platform == "windows":
        return "update.bat"
    if platform in PLATFORMS:
        return "update.sh"
    return None


def updater_bytes(name: str) -> bytes:
    path = Path(__file__).resolve().parent / "update_scripts" / name
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise PackageError("The update script is not available on this site.") from exc
    if not data:
        raise PackageError("The update script is not available on this site.")
    if name.endswith(".sh") and b"\r" in data:
        raise PackageError("The update script is not available on this site.")
    return data


def ensure_updater(path: Path, platform: str) -> bool:
    """Add the operator update script when a frozen zip does not have it.

    A script already stored at the zip root is left unchanged. Returns
    True when this call adds the file.
    """
    name = updater_name(platform)
    if name is None:
        return False
    data = updater_bytes(name)
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if _is_link(info) or _is_dir_entry(info):
                continue
            if _member_parts(info.filename) == [name]:
                return False
    info = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    if name.endswith(".sh"):
        info.create_system = 3
        info.external_attr = (stat.S_IFREG | 0o755) << 16
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr(info, data)
    return True

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


# Same five names as packaging/pyinstaller/executable_bundle.py in the Yaver repo.
# The office upload reads the version from these names.
_BUNDLE_FILES: tuple[tuple[str, str], ...] = (
    ("windows", "yaver-windows-x64-{version}.zip"),
    ("ubuntu-18.04", "yaver-linux-x64-ubuntu-18.04-{version}.zip"),
    ("ubuntu-20.04", "yaver-linux-x64-ubuntu-20.04-{version}.zip"),
    ("ubuntu-22.04", "yaver-linux-x64-ubuntu-22.04-{version}.zip"),
    ("ubuntu-24.04", "yaver-linux-x64-ubuntu-24.04-{version}.zip"),
)
_NAME_VERSION = re.compile(
    r"-(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.]+)?)\.zip$",
    re.IGNORECASE,
)


def bundle_member(filename: str) -> tuple[str, str] | None:
    """Return ``(platform, version)`` when ``filename`` is one of the five zips."""
    base = Path(filename or "").name
    found: list[tuple[str, str]] = []
    for platform, pattern in _BUNDLE_FILES:
        prefix, suffix = pattern.split("{version}")
        if not base.startswith(prefix) or not base.endswith(suffix):
            continue
        middle = base[len(prefix) : len(base) - len(suffix)]
        if _VERSION.fullmatch(middle):
            found.append((platform, middle))
    if len(found) == 1:
        return found[0]
    return None


def version_in_filename(filename: str) -> str | None:
    """Return a version at the end of a zip name, such as ``yaver-executables-0.9.79.zip``."""
    match = _NAME_VERSION.search(Path(filename or "").name)
    if match is None:
        return None
    text = match.group(1)
    if not _VERSION.fullmatch(text):
        return None
    return text


_NOTE_NAME = "RELEASE_NOTES.txt"
_MAX_NOTE_BYTES = 64 * 1024
_MAX_NOTE_CHARS = 32_000


def is_executable_bundle(path: Path) -> bool:
    """True when the zip holds versioned Yaver packages and an optional note.

    ``RELEASE_NOTES.txt`` is the only file that is not itself a zip.
    """
    if not zipfile.is_zipfile(path):
        return False
    names: list[str] = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if _is_link(info) or _is_dir_entry(info):
                continue
            parts = _member_parts(info.filename)
            if parts:
                names.append(parts[-1])
    if not names:
        return False
    zips = 0
    notes = 0
    for name in names:
        if name == _NOTE_NAME:
            notes += 1
            continue
        if name.lower().endswith(".zip"):
            zips += 1
            continue
        return False
    return zips > 0 and notes <= 1


def _release_note_text(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    """Read ``RELEASE_NOTES.txt``. Reject a huge, empty, or non-UTF-8 file."""
    if int(info.file_size) > _MAX_NOTE_BYTES:
        raise PackageError("The release note is too long.")
    chunks: list[bytes] = []
    total = 0
    with archive.open(info, "r") as src:
        while True:
            block = src.read(8192)
            if not block:
                break
            total += len(block)
            if total > _MAX_NOTE_BYTES:
                raise PackageError("The release note is too long.")
            chunks.append(block)
    raw = b"".join(chunks).replace(b"\x00", b"")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PackageError("The release note is not UTF-8 text.") from exc
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise PackageError("The release note is empty.")
    if len(text) > _MAX_NOTE_CHARS:
        raise PackageError("The release note is too long.")
    return text


def split_executable_bundle(
    path: Path,
    dest: Path,
    upload_name: str,
    typed_version: str = "",
) -> tuple[list[tuple[str, str, str, Path]], str]:
    """Extract the five versioned Yaver zips into ``dest``.

    Each returned path is a generated file name. The third item is the
    zip name from the upload, which is the name colleagues download.
    The second value is the text of ``RELEASE_NOTES.txt``, or ``""`` when
    that file is absent.
    """
    if not zipfile.is_zipfile(path):
        raise PackageError("The file is not a zip.")
    planned: list[tuple[zipfile.ZipInfo, str, str, str]] = []
    seen: dict[str, str] = {}
    note = ""
    note_seen = False
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise PackageError("The file is not a zip.") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > _MAX_MEMBERS:
            raise PackageError("The zip has too many files.")
        total = 0
        for info in infos:
            if _is_link(info):
                raise PackageError("The zip contains a symlink.")
            if _is_dir_entry(info):
                continue
            parts = _member_parts(info.filename)
            if not parts:
                continue
            if len(parts) != 1:
                raise PackageError("Put the Yaver zips at the top of the upload.")
            total += max(0, int(info.file_size))
            if total > _MAX_UNCOMPRESSED:
                raise PackageError("The zip expands to more than 16 GB.")
            base = parts[0]
            if base == _NOTE_NAME:
                if note_seen:
                    raise PackageError("The zip contains more than one release note.")
                note_seen = True
                note = _release_note_text(archive, info)
                continue
            if not base.lower().endswith(".zip"):
                raise PackageError(
                    "Upload the zip that contains the five versioned Yaver packages."
                )
            matched = bundle_member(base)
            if matched is None:
                raise PackageError(f"{base} is not a versioned Yaver package.")
            platform, version = matched
            if platform in seen:
                raise PackageError(
                    f"The zip contains more than one file for {package_label(platform)}."
                )
            seen[platform] = version
            planned.append((info, platform, version, base))
        if not planned:
            raise PackageError(
                "Upload the zip that contains the five versioned Yaver packages."
            )
        versions = set(seen.values())
        if len(versions) != 1:
            raise PackageError("These file names use more than one version.")
        version = next(iter(versions))
        typed = (typed_version or "").strip()
        if typed and typed != version:
            raise PackageError(f"The form says {typed}, and the zip names say {version}.")
        outer = version_in_filename(upload_name)
        if outer and outer != version:
            raise PackageError(
                f"{upload_name} says {outer}, and the files inside are {version}."
            )
        missing = [package_label(key) for key in PLATFORMS if key not in seen]
        if missing:
            raise PackageError("The zip is missing " + ", ".join(missing) + ".")
        dest.mkdir(parents=True, exist_ok=True)
        extracted: list[tuple[str, str, str, Path]] = []
        running = 0
        for index, (info, platform, member_version, base) in enumerate(planned):
            target = dest / f"{index}.zip"
            written = 0
            with archive.open(info, "r") as src, target.open("wb") as out:
                while True:
                    block = src.read(1024 * 1024)
                    if not block:
                        break
                    written += len(block)
                    running += len(block)
                    if written > _MAX_UNCOMPRESSED or running > _MAX_UNCOMPRESSED:
                        raise PackageError("The zip expands to more than 16 GB.")
                    out.write(block)
            extracted.append((platform, member_version, base, target))
    order = {key: index for index, key in enumerate(PLATFORMS)}
    extracted.sort(key=lambda item: order[item[0]])
    return extracted, note


def _is_cli(names: set[str]) -> bool:
    """One tool zip: its installer plus ``tool/tool`` or ``tool/tool.exe``."""
    for tool in ("opencode", "claude", "codex"):
        binary = f"{tool}/{tool}" in names or f"{tool}/{tool}.exe" in names
        installer = f"install-{tool}.sh" in names or f"install-{tool}.bat" in names
        if binary and installer:
            return True
    return False
