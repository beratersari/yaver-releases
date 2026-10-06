"""Freeze the release site and zip it the way Yaver zips are published.

The archive root is yaver-releases.exe, _internal, .env.example,
START_HERE.txt, and VERSION. The payload folder name is not a member.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SPEC = HERE / "yaver-releases.spec"


def _version() -> str:
    text = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not text:
        raise RuntimeError("VERSION is empty")
    return text


def _members(src_dir: Path) -> list[tuple[Path, str]]:
    """Files inside src_dir, named from that directory."""
    return [
        (path, path.relative_to(src_dir).as_posix())
        for path in src_dir.rglob("*")
        if path.is_file()
    ]


def write_zip(src_dir: Path, dest: Path) -> None:
    """Write a zip whose root is the files inside src_dir."""
    if dest.exists():
        dest.unlink()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, arcname in _members(src_dir):
            archive.write(path, arcname)


def main() -> int:
    if not SPEC.is_file():
        print(f"Missing spec: {SPEC}", file=sys.stderr)
        return 1
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. pip install pyinstaller", file=sys.stderr)
        return 1

    work = ROOT / "build" / "pyinstaller"
    dist_work = ROOT / "dist" / "pyinstaller"
    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(dist_work, ignore_errors=True)
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--distpath",
        str(dist_work),
        "--workpath",
        str(work),
        str(SPEC),
    ]
    print(" ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=str(ROOT))

    bundled = dist_work / "yaver-releases"
    exe = bundled / "yaver-releases.exe"
    if not exe.is_file() or not (bundled / "_internal").is_dir():
        print(f"Freeze finished but {exe} and _internal are missing", file=sys.stderr)
        return 1

    shutil.copy2(ROOT / ".env.example", bundled / ".env.example")
    shutil.copy2(HERE / "START_HERE.txt", bundled / "START_HERE.txt")
    shutil.copy2(ROOT / "VERSION", bundled / "VERSION")

    version = _version()
    payload = ROOT / "dist" / "stage" / f"yaver-releases-windows-x64-{version}"
    if payload.exists():
        shutil.rmtree(payload)
    shutil.copytree(bundled, payload)
    archive = ROOT / "dist" / f"yaver-releases-windows-x64-{version}.zip"
    write_zip(payload, archive)
    print(f"payload={payload}")
    print(f"archive={archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
