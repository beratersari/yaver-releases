"""Release site: public download, admin upload, and the latest-release API."""

from __future__ import annotations

import hashlib
import io
import os
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from yaver_releases.app import create_app
from yaver_releases.dotenv import load_dotenv
from yaver_releases.platforms import classify_members, flatten_wrapper


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        data_dir=tmp_path / "data",
        admin_user="admin",
        admin_password="correct-horse",
        secret="test-secret",
    )
    return TestClient(app)


def _zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def _csrf(html: str) -> str:
    marker = 'name="csrf" value="'
    start = html.index(marker) + len(marker)
    return html[start:html.index('"', start)]


def _sign_in(client: TestClient) -> None:
    page = client.get("/admin/login")
    assert page.status_code == 200
    token = _csrf(page.text)
    signed = client.post(
        "/admin/login",
        data={"username": "admin", "password": "correct-horse", "csrf": token},
        follow_redirects=False,
    )
    assert signed.status_code == 303
    assert signed.headers["location"] == "/admin"


def test_home_and_health_before_any_upload(tmp_path: Path):
    client = _client(tmp_path)
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {"ok": True}
    home = client.get("/")
    assert home.status_code == 200
    assert "Not published yet" in home.text
    assert "Install" in home.text
    assert 'href="/admin"' not in home.text
    login = client.get("/admin/login")
    assert login.status_code == 200
    assert 'href="/admin"' not in login.text
    css = client.get("/static/site.css")
    assert css.status_code == 200
    assert "Geist Variable" in css.text
    assert client.get("/static/yaver-wink.gif").status_code == 200
    missing = client.get("/api/latest?platform=windows")
    assert missing.status_code == 404
    assert client.get("/api/latest?platform=../windows").status_code == 404
    install = client.get("/install")
    assert install.status_code == 200
    assert 'href="/admin"' not in install.text
    assert "YAVER_BASE_DIR=/var/tmp/yaver" in install.text
    assert "yaver.exe" in install.text


def test_flatten_wrapper_removes_one_folder_and_keeps_a_flat_zip(tmp_path: Path):
    wrapped = tmp_path / "wrapped.zip"
    info = zipfile.ZipInfo("bundle/yaver")
    info.external_attr = 0o755 << 16
    info.create_system = 3
    with zipfile.ZipFile(wrapped, "w") as archive:
        archive.writestr(info, b"bin")
        archive.writestr("bundle/_internal/lib.so", b"so")
        archive.writestr("bundle/VERSION", b"1.0.0\n")
    assert flatten_wrapper(wrapped) is True
    with zipfile.ZipFile(wrapped) as archive:
        assert set(archive.namelist()) == {"yaver", "_internal/lib.so", "VERSION"}
        stored = archive.getinfo("yaver")
        assert stored.create_system == 3
        assert (stored.external_attr >> 16) & 0o777 == 0o755
    before = wrapped.read_bytes()
    assert flatten_wrapper(wrapped) is False
    assert wrapped.read_bytes() == before

    source = tmp_path / "source.zip"
    source.write_bytes(
        _zip(
            {
                "virtual_developer-linux/src/daemon.py": "x",
                "virtual_developer-linux/VERSION": "1.0.0",
                "virtual_developer-linux/install-dashboard.sh": "run",
            }
        )
    )
    assert flatten_wrapper(source) is True
    with zipfile.ZipFile(source) as archive:
        assert set(archive.namelist()) == {
            "src/daemon.py",
            "VERSION",
            "install-dashboard.sh",
        }

    with_dir = tmp_path / "dir.zip"
    with zipfile.ZipFile(with_dir, "w") as archive:
        archive.writestr("bundle/", "")
        archive.writestr("bundle/yaver.exe", b"x")
        archive.writestr("bundle/_internal/a", b"y")
    assert flatten_wrapper(with_dir) is True
    with zipfile.ZipFile(with_dir) as archive:
        assert set(archive.namelist()) == {"yaver.exe", "_internal/a"}

    mixed = tmp_path / "mixed.zip"
    mixed.write_bytes(_zip({"yaver.exe": "x", "_internal/a": "b", "notes/readme.txt": "n"}))
    original = mixed.read_bytes()
    assert flatten_wrapper(mixed) is False
    assert mixed.read_bytes() == original


def test_classify_executable_source_and_wrapped_folder():
    assert classify_members(["yaver.exe", "_internal/python.dll"]) == "frozen"
    assert classify_members(
        ["bundle/yaver", "bundle/_internal/lib.so", "bundle/VERSION"]
    ) == "frozen"
    assert classify_members(["src/daemon.py", "VERSION", "install-dashboard.sh"]) == "source"
    assert classify_members(["readme.txt"]) == "unknown"


def test_upload_requires_login_and_then_publishes(tmp_path: Path):
    client = _client(tmp_path)
    denied = client.post(
        "/admin/upload",
        data={"platform": "windows", "version": "0.9.72", "csrf": "nope"},
        files={"package": ("yaver.zip", _zip({"yaver.exe": "x", "_internal/a": "b"}), "application/zip")},
    )
    assert denied.status_code == 403

    _sign_in(client)
    admin = client.get("/admin")
    assert admin.status_code == 200
    token = _csrf(admin.text)
    payload = _zip(
        {
            "yaver-windows/yaver.exe": "new",
            "yaver-windows/_internal/marker": "1",
            "yaver-windows/.env.example": "JIRA_HOST=\n",
        }
    )
    published = client.post(
        "/admin/upload",
        data={
            "platform": "windows",
            "version": "0.9.72",
            "notes": "LAN build <script>alert(1)</script>",
            "csrf": token,
        },
        files={"package": ("yaver-windows.zip", payload, "application/zip")},
        follow_redirects=False,
    )
    assert published.status_code == 303

    latest = client.get("/api/latest?platform=windows")
    assert latest.status_code == 200
    body = latest.json()
    assert body["version"] == "0.9.72"
    assert body["layout"] == "frozen"
    assert body["filename"] == "yaver-windows.zip"
    assert body["download_path"] == "/download/windows"
    assert len(body["sha256"]) == 64

    downloaded = client.get("/download/windows")
    assert downloaded.status_code == 200
    assert hashlib.sha256(downloaded.content).hexdigest() == body["sha256"]
    assert body["size"] == len(downloaded.content)
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        assert set(archive.namelist()) == {
            "yaver.exe",
            "_internal/marker",
            ".env.example",
        }
    assert "yaver-windows.zip" in downloaded.headers["content-disposition"]

    home = client.get("/")
    assert "0.9.72" in home.text
    assert "<script>alert" not in home.text
    assert "&lt;script&gt;" in home.text


def test_a_latest_named_zip_publishes_the_version_file(tmp_path: Path):
    client = _client(tmp_path)
    _sign_in(client)
    admin = client.get("/admin")
    token = _csrf(admin.text)
    payload = _zip(
        {
            "bundle/yaver.exe": "bin",
            "bundle/_internal/a": "x",
            "bundle/VERSION": "\ufeff0.9.73\n",
        }
    )
    published = client.post(
        "/admin/upload",
        data={"platform": "windows", "version": "", "csrf": token},
        files={"package": ("yaver-windows-latest.zip", payload, "application/zip")},
        follow_redirects=False,
    )
    assert published.status_code == 303
    body = client.get("/api/latest?platform=windows").json()
    assert body["version"] == "0.9.73"
    assert body["filename"] == "yaver-windows-latest.zip"
    assert "latest" in body["filename"]
    with zipfile.ZipFile(io.BytesIO(client.get("/download/windows").content)) as archive:
        assert archive.read("VERSION").decode("utf-8-sig").strip() == "0.9.73"

    admin = client.get("/admin")
    token = _csrf(admin.text)
    mismatch = client.post(
        "/admin/upload",
        data={"platform": "ubuntu-22.04", "version": "0.9.70", "csrf": token},
        files={
            "package": (
                "yaver-ubuntu-22.04-latest.zip",
                _zip({"yaver": "b", "_internal/a": "x", "VERSION": "0.9.73\n"}),
                "application/zip",
            )
        },
    )
    assert mismatch.status_code == 400
    assert "The VERSION file says 0.9.73." in mismatch.text
    assert client.get("/api/latest?platform=ubuntu-22.04").status_code == 404

    admin = client.get("/admin")
    token = _csrf(admin.text)
    missing = client.post(
        "/admin/upload",
        data={"platform": "ubuntu-20.04", "version": " ", "csrf": token},
        files={
            "package": (
                "yaver-ubuntu-20.04-latest.zip",
                _zip({"yaver": "b", "_internal/a": "x"}),
                "application/zip",
            )
        },
    )
    assert missing.status_code == 400
    assert "VERSION file" in missing.text


def test_rejects_zip_slip_bad_version_and_replaces_the_previous_file(tmp_path: Path):
    client = _client(tmp_path)
    _sign_in(client)
    admin = client.get("/admin")
    token = _csrf(admin.text)
    slipped = _zip({"../outside.txt": "no"})
    rejected = client.post(
        "/admin/upload",
        data={"platform": "ubuntu-22.04", "version": "1.2.3", "csrf": token},
        files={"package": ("bad.zip", slipped, "application/zip")},
    )
    assert rejected.status_code == 400
    assert "parent path" in rejected.text
    assert client.get("/api/latest?platform=ubuntu-22.04").status_code == 404

    admin = client.get("/admin")
    token = _csrf(admin.text)
    bad_version = client.post(
        "/admin/upload",
        data={"platform": "ubuntu-22.04", "version": "latest", "csrf": token},
        files={
            "package": (
                "ok.zip",
                _zip({"src/daemon.py": "x", "VERSION": "1.0.0"}),
                "application/zip",
            )
        },
    )
    assert bad_version.status_code == 400

    admin = client.get("/admin")
    token = _csrf(admin.text)
    first = _zip({"src/daemon.py": "one", "VERSION": "1.0.0"})
    ok = client.post(
        "/admin/upload",
        data={"platform": "ubuntu-22.04", "version": "1.0.0", "csrf": token},
        files={"package": ("linux.zip", first, "application/zip")},
        follow_redirects=True,
    )
    assert ok.status_code == 200
    assert "Install zip" in ok.text
    files = list((tmp_path / "data" / "files").glob("*.zip"))
    assert len(files) == 1

    admin = client.get("/admin")
    token = _csrf(admin.text)
    second = _zip({"src/daemon.py": "two", "VERSION": "1.0.1"})
    replaced = client.post(
        "/admin/upload",
        data={"platform": "ubuntu-22.04", "version": "1.0.1", "csrf": token},
        files={"package": ("linux.zip", second, "application/zip")},
        follow_redirects=False,
    )
    assert replaced.status_code == 303
    assert client.get("/download/ubuntu-22.04").content == second
    files = list((tmp_path / "data" / "files").glob("*.zip"))
    assert len(files) == 1

    admin = client.get("/admin")
    token = _csrf(admin.text)
    removed = client.post(
        "/admin/delete",
        data={"platform": "ubuntu-22.04", "csrf": token},
        follow_redirects=False,
    )
    assert removed.status_code == 303
    assert client.get("/api/latest?platform=ubuntu-22.04").status_code == 404


def test_wrong_password_does_not_sign_in(tmp_path: Path):
    client = _client(tmp_path)
    page = client.get("/admin/login")
    token = _csrf(page.text)
    failed = client.post(
        "/admin/login",
        data={"username": "admin", "password": "nope", "csrf": token},
        follow_redirects=False,
    )
    assert failed.status_code == 400
    assert "Wrong username or password" in failed.text
    assert client.get("/admin", follow_redirects=False).status_code == 303


def test_dotenv_does_not_override_the_environment(tmp_path: Path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "YAVER_RELEASE_PORT=8091\nYAVER_RELEASE_ADMIN_USER=from-file\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("YAVER_RELEASE_ADMIN_USER", "already")
    monkeypatch.delenv("YAVER_RELEASE_PORT", raising=False)
    load_dotenv(env)
    assert os.environ["YAVER_RELEASE_ADMIN_USER"] == "already"
    assert os.environ["YAVER_RELEASE_PORT"] == "8091"


def test_login_without_a_password_configured(tmp_path: Path):
    app = create_app(
        data_dir=tmp_path / "data",
        admin_user="",
        admin_password="",
        secret="test-secret",
    )
    client = TestClient(app)
    page = client.get("/admin/login")
    assert "no default password" in page.text
    token = _csrf(page.text)
    failed = client.post(
        "/admin/login",
        data={"username": "admin", "password": "x", "csrf": token},
    )
    assert failed.status_code == 400
    assert "YAVER_RELEASE_ADMIN_PASSWORD" in failed.text
