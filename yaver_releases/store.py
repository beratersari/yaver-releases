"""One published zip per platform. Files live next to a small SQLite catalog."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from yaver_releases.platforms import PLATFORMS


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class ReleaseStore:
    def __init__(self, root: Path):
        self.root = root
        self.files = root / "files"
        self.db_path = root / "releases.sqlite"
        self.files.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS releases (
                    platform TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    stored_name TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    layout TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    uploaded_at TEXT NOT NULL
                )
                """
            )

    def get(self, platform: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM releases WHERE platform = ?",
                (platform,),
            ).fetchone()
        if row is None:
            return None
        return self._public(row)

    def list_all(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM releases ORDER BY platform"
            ).fetchall()
        by_platform = {row["platform"]: row for row in rows}
        out: list[dict] = []
        for platform in PLATFORMS:
            row = by_platform.get(platform)
            if row is None:
                out.append(
                    {
                        "platform": platform,
                        "label": PLATFORMS[platform],
                        "version": "",
                        "filename": "",
                        "sha256": "",
                        "size": 0,
                        "layout": "",
                        "notes": "",
                        "published_at": "",
                        "download_path": "",
                    }
                )
            else:
                out.append(self._public(row))
        return out

    def blob_path(self, platform: str) -> Path | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT stored_name FROM releases WHERE platform = ?",
                (platform,),
            ).fetchone()
        if row is None:
            return None
        path = (self.files / str(row["stored_name"])).resolve()
        files = self.files.resolve()
        if files != path and files not in path.parents:
            return None
        if not path.is_file():
            return None
        return path

    def publish(
        self,
        *,
        platform: str,
        version: str,
        filename: str,
        sha256: str,
        size: int,
        layout: str,
        notes: str,
        blob: Path,
    ) -> dict:
        stored_name = f"{platform}-{version}-{sha256[:12]}.zip"
        dest = self.files / stored_name
        previous = self.blob_path(platform)
        shutil.copyfile(blob, dest)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO releases (
                    platform, version, filename, stored_name, sha256, size,
                    layout, notes, uploaded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform) DO UPDATE SET
                    version = excluded.version,
                    filename = excluded.filename,
                    stored_name = excluded.stored_name,
                    sha256 = excluded.sha256,
                    size = excluded.size,
                    layout = excluded.layout,
                    notes = excluded.notes,
                    uploaded_at = excluded.uploaded_at
                """,
                (
                    platform,
                    version,
                    filename,
                    stored_name,
                    sha256,
                    int(size),
                    layout,
                    notes,
                    _now(),
                ),
            )
        if previous is not None and previous.resolve() != dest.resolve():
            try:
                previous.unlink()
            except OSError:
                pass
        published = self.get(platform)
        if published is None:
            raise RuntimeError("The release was not stored.")
        return published

    def delete(self, platform: str) -> None:
        path = self.blob_path(platform)
        with self._connect() as conn:
            conn.execute("DELETE FROM releases WHERE platform = ?", (platform,))
        if path is not None:
            try:
                path.unlink()
            except OSError:
                pass

    def _public(self, row: sqlite3.Row) -> dict:
        platform = str(row["platform"])
        return {
            "platform": platform,
            "label": PLATFORMS.get(platform, platform),
            "version": str(row["version"]),
            "filename": str(row["filename"]),
            "sha256": str(row["sha256"]),
            "size": int(row["size"]),
            "layout": str(row["layout"]),
            "notes": str(row["notes"]),
            "published_at": str(row["uploaded_at"]),
            "download_path": f"/download/{platform}",
        }
