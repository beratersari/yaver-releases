"""Published zips, including older versions. Files live next to a small SQLite catalog.

``/download/{platform}`` is the newest zip for that platform. Release history
keeps every version that was published.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from yaver_releases.platforms import DEPENDENCIES, PLATFORMS, ensure_updater, package_label


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _version_key(version: str) -> tuple[int, ...]:
    """Sort ``0.9.9`` before ``0.9.72`` and both before ``0.10.0``."""
    head = (version or "").split("+", 1)[0].split("-", 1)[0]
    numbers: list[int] = []
    for piece in head.split("."):
        if piece.isdigit():
            numbers.append(int(piece))
        else:
            numbers.append(-1)
    return tuple(numbers)


def _file_sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


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
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'releases'"
            ).fetchone()
            if exists is None:
                self._create_releases(conn)
            else:
                info = conn.execute("PRAGMA table_info(releases)").fetchall()
                primary = [str(col["name"]) for col in info if int(col["pk"]) > 0]
                if primary == ["platform"]:
                    conn.execute("ALTER TABLE releases RENAME TO releases_platform_pk")
                    self._create_releases(conn)
                    conn.execute(
                        """
                        INSERT INTO releases (
                            platform, version, filename, stored_name, sha256, size,
                            layout, notes, uploaded_at
                        )
                        SELECT platform, version, filename, stored_name, sha256, size,
                               layout, notes, uploaded_at
                        FROM releases_platform_pk
                        """
                    )
                    conn.execute("DROP TABLE releases_platform_pk")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS page_copy (
                    key TEXT PRIMARY KEY,
                    body TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _create_releases(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE releases (
                platform TEXT NOT NULL,
                version TEXT NOT NULL,
                filename TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                size INTEGER NOT NULL,
                layout TEXT NOT NULL,
                notes TEXT NOT NULL,
                uploaded_at TEXT NOT NULL,
                PRIMARY KEY (platform, version)
            )
            """
        )

    def get(self, platform: str) -> dict | None:
        row = self._latest_row(platform)
        if row is None:
            return None
        return self._public(row)

    def get_version(self, platform: str, version: str) -> dict | None:
        row = self._exact_row(platform, version)
        if row is None:
            return None
        public = self._public(row)
        public["download_path"] = f"/download/{platform}/{version}"
        return public

    def list_all(self) -> list[dict]:
        return self._catalog(PLATFORMS, self._latest_by_platform())

    def list_dependencies(self) -> list[dict]:
        return self._catalog(DEPENDENCIES, self._latest_by_platform())

    def list_history(self) -> list[dict]:
        """Yaver packages grouped by version, newest version first."""
        order = {name: index for index, name in enumerate(PLATFORMS)}
        groups: dict[str, list[dict]] = {}
        for row in self._rows():
            platform = str(row["platform"])
            if platform not in PLATFORMS or not str(row["version"]):
                continue
            public = self._public(row)
            public["download_path"] = f"/download/{platform}/{public['version']}"
            groups.setdefault(public["version"], []).append(public)
        history: list[dict] = []
        for version in sorted(groups, key=_version_key, reverse=True):
            packages = sorted(groups[version], key=lambda item: order.get(str(item["platform"]), 99))
            filled = [str(item.get("notes") or "") for item in packages if str(item.get("notes") or "").strip()]
            shared = filled[0] if filled and all(item == filled[0] for item in filled) else ""
            history.append({"version": version, "packages": packages, "notes": shared})
        return history

    def _rows(self) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return list(conn.execute("SELECT * FROM releases").fetchall())

    def _latest_by_platform(self) -> dict[str, sqlite3.Row]:
        chosen: dict[str, sqlite3.Row] = {}
        for row in self._rows():
            platform = str(row["platform"])
            current = chosen.get(platform)
            if current is None or _version_key(str(row["version"])) >= _version_key(str(current["version"])):
                chosen[platform] = row
        return chosen

    def _latest_row(self, platform: str) -> sqlite3.Row | None:
        return self._latest_by_platform().get(platform)

    def _exact_row(self, platform: str, version: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM releases WHERE platform = ? AND version = ?",
                (platform, version),
            ).fetchone()

    def _catalog(self, labels: dict[str, str], by_platform: dict) -> list[dict]:
        out: list[dict] = []
        for platform, label in labels.items():
            row = by_platform.get(platform)
            if row is None:
                out.append(
                    {
                        "platform": platform,
                        "label": label,
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

    def blob_path(self, platform: str, version: str | None = None) -> Path | None:
        row = self._exact_row(platform, version) if version else self._latest_row(platform)
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
        previous = self.blob_path(platform, version)
        shutil.copyfile(blob, dest)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO releases (
                    platform, version, filename, stored_name, sha256, size,
                    layout, notes, uploaded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, version) DO UPDATE SET
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

    def publish_many(self, items: list[dict]) -> None:
        """Publish every package, or leave the previous files in place.

        New files are copied first. The catalog changes in one transaction.
        A failure deletes only the copies this call added.
        """
        staged: list[tuple[Path, Path | None]] = []
        rows: list[tuple] = []
        now = _now()
        try:
            for item in items:
                platform = str(item["platform"])
                version = str(item["version"])
                sha = str(item["sha256"])
                stored_name = f"{platform}-{version}-{sha[:12]}.zip"
                dest = self.files / stored_name
                previous = self.blob_path(platform, version)
                if previous is None or previous.resolve() != dest.resolve():
                    shutil.copyfile(item["blob"], dest)
                staged.append((dest, previous))
                rows.append(
                    (
                        platform,
                        version,
                        str(item["filename"]),
                        stored_name,
                        sha,
                        int(item["size"]),
                        str(item["layout"]),
                        str(item["notes"]),
                        now,
                    )
                )
            with self._connect() as conn:
                for row in rows:
                    conn.execute(
                        """
                        INSERT INTO releases (
                            platform, version, filename, stored_name, sha256, size,
                            layout, notes, uploaded_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(platform, version) DO UPDATE SET
                            filename = excluded.filename,
                            stored_name = excluded.stored_name,
                            sha256 = excluded.sha256,
                            size = excluded.size,
                            layout = excluded.layout,
                            notes = excluded.notes,
                            uploaded_at = excluded.uploaded_at
                        """,
                        row,
                    )
        except Exception:
            for dest, previous in staged:
                if previous is not None and previous.resolve() == dest.resolve():
                    continue
                try:
                    dest.unlink()
                except OSError:
                    pass
            raise
        for dest, previous in staged:
            if previous is None or previous.resolve() == dest.resolve():
                continue
            try:
                previous.unlink()
            except OSError:
                pass

    def add_missing_updaters(self) -> list[str]:
        """Put the update script into frozen zips that were stored without it."""
        changed: list[str] = []
        for row in self._rows():
            if str(row["layout"]) != "frozen" or not str(row["version"]):
                continue
            platform = str(row["platform"])
            version = str(row["version"])
            path = self.blob_path(platform, version)
            if path is None or not ensure_updater(path, platform):
                continue
            digest, size = _file_sha256(path)
            stored_name = f"{platform}-{version}-{digest[:12]}.zip"
            dest = self.files / stored_name
            if dest.resolve() != path.resolve():
                if dest.exists():
                    raise RuntimeError(f"Release file already exists: {stored_name}")
                os.replace(path, dest)
            self._remember_blob(platform, version, stored_name, digest, size)
            changed.append(platform)
        return changed

    def _remember_blob(
        self,
        platform: str,
        version: str,
        stored_name: str,
        sha256: str,
        size: int,
    ) -> None:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE releases
                SET stored_name = ?, sha256 = ?, size = ?
                WHERE platform = ? AND version = ?
                """,
                (stored_name, sha256, int(size), platform, version),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("The release was not stored.")

    def copy_map(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, body FROM page_copy").fetchall()
        return {str(row["key"]): str(row["body"]) for row in rows}

    def save_copy(self, updates: dict[str, str]) -> None:
        now = _now()
        with self._connect() as conn:
            for key, body in updates.items():
                conn.execute(
                    """
                    INSERT INTO page_copy (key, body, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        body = excluded.body,
                        updated_at = excluded.updated_at
                    """,
                    (key, body, now),
                )

    def clear_copy(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM page_copy")

    def delete(self, platform: str) -> None:
        paths = [
            self.files / str(row["stored_name"])
            for row in self._rows()
            if str(row["platform"]) == platform
        ]
        with self._connect() as conn:
            conn.execute("DELETE FROM releases WHERE platform = ?", (platform,))
        for path in paths:
            try:
                path.unlink()
            except OSError:
                pass

    def _public(self, row: sqlite3.Row) -> dict:
        platform = str(row["platform"])
        return {
            "platform": platform,
            "label": package_label(platform),
            "version": str(row["version"]),
            "filename": str(row["filename"]),
            "sha256": str(row["sha256"]),
            "size": int(row["size"]),
            "layout": str(row["layout"]),
            "notes": str(row["notes"]),
            "published_at": str(row["uploaded_at"]),
            "download_path": f"/download/{platform}",
        }
