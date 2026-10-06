"""The published zip root matches a Yaver executable archive."""

from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path


def _build():
    path = Path(__file__).resolve().parents[1] / "packaging" / "pyinstaller" / "build.py"
    spec = importlib.util.spec_from_file_location("yaver_releases_build", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_zip_root_is_the_executable_and_env_example(tmp_path: Path):
    payload = tmp_path / "payload"
    (payload / "_internal").mkdir(parents=True)
    (payload / "_internal" / "python.dll").write_bytes(b"dll")
    (payload / "yaver-releases.exe").write_bytes(b"exe")
    (payload / ".env.example").write_text("YAVER_RELEASE_PORT=8090\n", encoding="utf-8")
    (payload / "START_HERE.txt").write_text("Copy .env.example to .env\n", encoding="utf-8")
    (payload / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    dest = tmp_path / "yaver-releases-windows-x64-1.0.0.zip"
    _build().write_zip(payload, dest)
    with zipfile.ZipFile(dest) as archive:
        names = set(archive.namelist())
    assert "yaver-releases.exe" in names
    assert ".env.example" in names
    assert "START_HERE.txt" in names
    assert "VERSION" in names
    assert "_internal/python.dll" in names
    assert all(not name.startswith("payload/") for name in names)
