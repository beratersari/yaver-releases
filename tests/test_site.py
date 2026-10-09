"""Release site: public download, admin upload, and the latest-release API."""

from __future__ import annotations

import hashlib
import html as html_lib
import hmac
import io
import json
import os
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from yaver_releases.app import create_app
from yaver_releases.install_fetch import INSTALL_ANALYTICS_TOKEN
from yaver_releases.dotenv import load_dotenv
from yaver_releases.platforms import classify_members, flatten_wrapper, updater_bytes


@pytest.fixture(autouse=True)
def _do_not_call_a_live_dashboard(monkeypatch):
    """Analytics fetches in these tests must not open port 8080."""
    monkeypatch.setattr("yaver_releases.install_fetch.INSTALL_ANALYTICS_PORT", 9)


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
    assert "LAN releases" not in home.text
    assert "Install" in home.text
    assert 'href="/admin"' not in home.text
    assert home.text.index(">Install<") < home.text.index(">Release history<") < home.text.index(">Dependencies<")
    releases = client.get("/releases")
    assert releases.status_code == 200
    assert "Release history" in releases.text
    assert "No release has been published." in releases.text
    assert "<h1>Release history</h1>" in releases.text
    login = client.get("/admin/login")
    assert login.status_code == 200
    assert 'href="/admin"' not in login.text
    css = client.get("/static/site.css")
    assert css.status_code == 200
    assert "Geist Variable" in css.text
    assert "max-width: 42rem" not in css.text
    assert "max-width: 36rem" not in css.text
    assert "#f5c451" not in css.text
    assert "--warn: #e8b84a" in css.text
    assert client.get("/static/yaver-wink.gif").status_code == 200
    missing = client.get("/api/latest?platform=windows")
    assert missing.status_code == 404
    assert client.get("/api/latest?platform=../windows").status_code == 404
    install = client.get("/install")
    assert install.status_code == 200
    assert "You must install OpenCode to use Yaver." in install.text
    assert "Claude Code and Codex are optional." in install.text
    assert install.text.index("You must install OpenCode") < install.text.index('id="windows"')
    assert 'href="/dependencies#opencode"' in install.text
    script = client.get("/static/theme.js")
    assert script.status_code == 200
    assert "fold.open = true" in script.text
    assert 'document.getElementById' in script.text
    assert 'href="/dependencies#claude"' in install.text
    assert 'href="/dependencies#codex"' in install.text
    assert 'href="/admin"' not in install.text
    assert "Install zip" not in install.text
    assert "cannot reach this IP" not in install.text
    assert "Run this site" not in install.text
    assert "install-dashboard" not in install.text
    assert "Settings, then Runtime" not in install.text
    assert "http://testserver/download/windows" in install.text
    assert "http://testserver/download/ubuntu-22.04" in install.text
    assert "curl.exe -fL" in install.text
    assert "tar.exe -xf yaver-windows.zip -C yaver" in install.text
    assert install.text.count("<details") == 5
    assert 'id="opencode"' not in install.text
    assert "install-opencode.bat" not in install.text
    tools = client.get("/dependencies")
    assert tools.status_code == 200
    assert tools.text.count("<details") == 3
    assert 'id="opencode"' in tools.text
    assert 'id="claude"' in tools.text
    assert 'id="codex"' in tools.text
    assert tools.text.index('id="opencode"') < tools.text.index('id="claude"')
    assert tools.text.index('id="claude"') < tools.text.index('id="codex"')
    assert "http://testserver/download/opencode-windows" in tools.text
    assert "http://testserver/download/opencode-linux" in tools.text
    assert "http://testserver/download/claude-windows" in tools.text
    assert "http://testserver/download/claude-linux" in tools.text
    assert "http://testserver/download/codex-windows" in tools.text
    assert "http://testserver/download/codex-linux" in tools.text
    assert ".\\install-opencode.bat" in tools.text
    assert "./install-opencode.sh" in tools.text
    assert ".\\install-claude.bat" in tools.text
    assert "./install-claude.sh" in tools.text
    assert ".\\install-codex.bat" in tools.text
    assert "./install-codex.sh" in tools.text
    assert "OpenCode" in tools.text
    assert "Claude Code" in tools.text
    assert "Codex" in tools.text
    assert "install-opencode.bat" not in home.text
    assert "install-claude.sh" not in home.text
    assert "install-codex.bat" not in home.text
    assert "/download/opencode-windows" not in home.text
    assert "Windows package is not published yet." not in home.text
    assert "Windows package is not published yet." not in install.text
    assert tools.text.count("<h3>Windows</h3>") == 4
    assert tools.text.count("<h3>Linux</h3>") == 4
    assert tools.text.index('id="codex"') < tools.text.index('id="artifacts"')
    assert ">Artifacts</h2>" in tools.text
    assert "No package has been published yet." in tools.text
    assert '<a class="button"' not in tools.text
    assert install.text.count("<h3>Install</h3>") == 5
    assert install.text.count("<h3>Update</h3>") == 5
    assert install.text.count("setsid nohup ./yaver start") == 4
    assert install.text.count("nano .env") == 5
    assert "notepad .env" in install.text
    assert ".\\install-agents.bat" in install.text
    assert install.text.count("./install-agents.sh") == 4
    assert install.text.count("./update.sh") == 4
    windows_at = install.text.index('id="windows"')
    windows_update = install.text.index("update.bat")
    ubuntu18 = install.text.index('id="ubuntu-18.04"')
    ubuntu22 = install.text.index('id="ubuntu-22.04"')
    ubuntu24 = install.text.index('id="ubuntu-24.04"')
    assert windows_at < windows_update < ubuntu18 < ubuntu22 < ubuntu24
    ubuntu22_block = install.text[ubuntu22:ubuntu24]
    assert "unzip -o /tmp/yaver-22.04.zip" in ubuntu22_block
    assert "nano .env" in ubuntu22_block
    assert "./install-agents.sh" in ubuntu22_block
    assert "sudo ufw allow 8080" in ubuntu22_block
    assert "8080/tcp" not in ubuntu22_block
    assert "8080/udp" not in ubuntu22_block
    assert install.text.count("sudo ufw allow 8080") == 4
    assert ubuntu22_block.index("./install-agents.sh") < ubuntu22_block.index("nano .env")
    assert ubuntu22_block.index("nano .env") < ubuntu22_block.index("sudo ufw allow 8080")
    windows_block = install.text[windows_at:ubuntu18]
    assert windows_block.index("install-agents.bat") < windows_block.index("notepad .env")
    assert "./update.sh" in ubuntu22_block
    assert "yaver-18.04.zip" not in ubuntu22_block
    assert "Start again later" not in install.text
    assert "Start-Process" not in install.text
    assert "&lt; /dev/null" in install.text
    assert "< /dev/null" not in install.text
    assert "unzip -o /tmp/yaver-22.04.zip" in install.text
    assert "update.bat" in install.text
    assert install.text.count('class="warn"') == 5
    assert install.text.count("<strong>Warning</strong>:") == 5
    assert "<strong>Warning</strong>." not in install.text
    assert "DASHBOARD_USERNAME" in install.text
    assert "DASHBOARD_PASSWORD" in install.text
    windows_warn = install.text.index('class="warn"', windows_at)
    windows_command = install.text.index("curl.exe", windows_at)
    assert windows_at < windows_warn < windows_command
    ubuntu_warn = install.text.index('class="warn"', ubuntu22)
    ubuntu_command = install.text.index("mkdir -p", ubuntu22)
    assert ubuntu22 < ubuntu_warn < ubuntu_command
    assert "Start yaver.exe after the script prints Updated to." not in install.text
    assert "If update.bat is not in the folder yet" not in install.text
    assert "prints Updated to" not in install.text
    assert "is not in the folder yet" not in install.text
    assert "chmod 755 update.sh" in install.text
    assert "./update.sh" in install.text
    assert "yaver update" not in install.text
    assert "--host" not in install.text
    assert "--port" not in install.text
    assert "Copy-Item .env.example .env" in install.text
    assert "Update from Settings" not in home.text
    assert "update.bat" in home.text
    assert "update.sh" in home.text
    assert "yaver update" not in home.text


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
    assert classify_members(
        [
            "install-opencode.bat",
            "Backup-CliBinary.ps1",
            "opencode/opencode.exe",
            "opencode/opencode.json",
            "VERSION",
        ]
    ) == "cli"
    assert classify_members(
        ["tool/install-claude.sh", "tool/lib.sh", "tool/claude/claude", "tool/VERSION"]
    ) == "cli"
    assert classify_members(
        ["install-codex.sh", "codex/codex", "codex/config.toml", "VERSION"]
    ) == "cli"


def test_a_cli_zip_is_a_dependency_and_not_a_yaver_update(tmp_path: Path):
    client = _client(tmp_path)
    _sign_in(client)
    admin = client.get("/admin")
    assert 'value="opencode-windows"' in admin.text
    assert "OpenCode for Windows" in admin.text
    token = _csrf(admin.text)
    payload = _zip(
        {
            "install-opencode.bat": "@echo off\r\n",
            "Backup-CliBinary.ps1": "# backup\n",
            "opencode/opencode.exe": "bin",
            "opencode/opencode.json": "{}\n",
            "VERSION": "1.18.10\n",
        }
    )
    published = client.post(
        "/admin/upload",
        data={"platform": "opencode-windows", "version": "", "csrf": token},
        files={"package": ("opencode-windows.zip", payload, "application/zip")},
        follow_redirects=False,
    )
    assert published.status_code == 303
    assert client.get("/api/latest?platform=opencode-windows").status_code == 404
    catalog = client.get("/api/releases").json()
    row = next(item for item in catalog["dependencies"] if item["platform"] == "opencode-windows")
    assert row["version"] == "1.18.10"
    assert row["layout"] == "cli"
    assert row["download_path"] == "/download/opencode-windows"
    assert all(item["platform"] != "opencode-windows" for item in catalog["releases"])
    downloaded = client.get("/download/opencode-windows")
    assert downloaded.status_code == 200
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        assert "update.bat" not in archive.namelist()
        assert "update.sh" not in archive.namelist()
    tools = client.get("/dependencies")
    assert "1.18.10" in tools.text
    assert "Command-line tool" in tools.text
    assert 'href="/download/opencode-windows"' in tools.text
    assert ".\\install-opencode.bat" in tools.text
    fold = tools.text[tools.text.index('id="opencode"'):tools.text.index('id="artifacts"')]
    assert 'href="/download/opencode-windows"' not in fold
    artifacts = tools.text[tools.text.index('id="artifacts"'):]
    assert ">Artifacts</h2>" in artifacts
    assert artifacts.index(">Artifacts</h2>") < artifacts.index('href="/download/opencode-windows"')
    assert "Download 1.18.10" in artifacts
    install = client.get("/install")
    assert ".\\install-opencode.bat" not in install.text
    assert "1.18.10" not in install.text
    assert "Command-line tool" not in install.text
    assert client.get("/api/latest?platform=windows").status_code == 404


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
            "update.bat",
        }
        assert archive.read("update.bat") == updater_bytes("update.bat")
    assert "yaver-windows.zip" in downloaded.headers["content-disposition"]

    history = client.get("/releases")
    assert "0.9.72" in history.text
    assert 'href="/download/windows/0.9.72"' in history.text
    assert "<details" in history.text
    assert "<script>alert" not in history.text
    assert "&lt;script&gt;" in history.text


def test_upload_keeps_an_update_script_already_in_the_zip(tmp_path: Path):
    client = _client(tmp_path)
    _sign_in(client)
    token = _csrf(client.get("/admin").text)
    custom = b"@echo off\r\nrem already published\r\n"
    published = client.post(
        "/admin/upload",
        data={"platform": "windows", "version": "0.9.72", "csrf": token},
        files={
            "package": (
                "yaver.zip",
                _zip({"yaver.exe": "x", "_internal/a": "b", "update.bat": custom.decode("ascii")}),
                "application/zip",
            )
        },
        follow_redirects=False,
    )
    assert published.status_code == 303
    with zipfile.ZipFile(io.BytesIO(client.get("/download/windows").content)) as archive:
        assert archive.read("update.bat") == custom
        assert archive.namelist().count("update.bat") == 1


def test_ubuntu_upload_adds_update_sh(tmp_path: Path):
    client = _client(tmp_path)
    _sign_in(client)
    token = _csrf(client.get("/admin").text)
    published = client.post(
        "/admin/upload",
        data={"platform": "ubuntu-22.04", "version": "0.9.72", "csrf": token},
        files={
            "package": (
                "yaver.zip",
                _zip({"yaver": "bin", "_internal/a": "x"}),
                "application/zip",
            )
        },
        follow_redirects=False,
    )
    assert published.status_code == 303
    with zipfile.ZipFile(io.BytesIO(client.get("/download/ubuntu-22.04").content)) as archive:
        info = archive.getinfo("update.sh")
        assert archive.read("update.sh") == updater_bytes("update.sh")
        assert (info.external_attr >> 16) & 0o777 == 0o755


def test_a_source_zip_does_not_gain_an_update_script(tmp_path: Path):
    client = _client(tmp_path)
    _sign_in(client)
    token = _csrf(client.get("/admin").text)
    published = client.post(
        "/admin/upload",
        data={"platform": "windows", "version": "0.9.72", "csrf": token},
        files={
            "package": (
                "src.zip",
                _zip({"src/daemon.py": "x", "VERSION": "0.9.72\n"}),
                "application/zip",
            )
        },
        follow_redirects=False,
    )
    assert published.status_code == 303
    with zipfile.ZipFile(io.BytesIO(client.get("/download/windows").content)) as archive:
        assert "update.bat" not in archive.namelist()


def test_stored_frozen_zip_gains_the_update_script(tmp_path: Path):
    from yaver_releases.store import ReleaseStore

    store = ReleaseStore(tmp_path)
    blob = tmp_path / "yaver.zip"
    with zipfile.ZipFile(blob, "w") as archive:
        archive.writestr("yaver.exe", b"exe")
        archive.writestr("_internal/a", b"a")
    raw = blob.read_bytes()
    store.publish(
        platform="windows",
        version="0.9.72",
        filename="yaver-windows.zip",
        sha256=hashlib.sha256(raw).hexdigest(),
        size=len(raw),
        layout="frozen",
        notes="",
        blob=blob,
    )
    assert store.add_missing_updaters() == ["windows"]
    path = store.blob_path("windows")
    assert path is not None
    file_bytes = path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
        assert archive.read("update.bat") == updater_bytes("update.bat")
        assert archive.read("yaver.exe") == b"exe"
    row = store.get("windows")
    assert row is not None
    assert row["filename"] == "yaver-windows.zip"
    assert row["sha256"] == hashlib.sha256(file_bytes).hexdigest()
    assert row["size"] == len(file_bytes)
    assert store.add_missing_updaters() == []


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
    assert client.get("/download/ubuntu-22.04/1.0.0").content == first
    history = client.get("/releases")
    assert 'id="release-1.0.1"' in history.text
    assert 'id="release-1.0.0"' in history.text
    assert history.text.index('id="release-1.0.1"') < history.text.index('id="release-1.0.0"')
    files = list((tmp_path / "data" / "files").glob("*.zip"))
    assert len(files) == 2

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


def test_admin_can_replace_page_text_and_restore_it(tmp_path: Path):
    from yaver_releases.copy import DEFAULTS, render_copy, fill

    escaped = render_copy(fill('curl {windows}\n<script>\n[bad](javascript:alert(1))', {"windows": "http://x/<script>"}))
    assert "<script>" not in escaped
    assert "&lt;script&gt;" in escaped
    assert 'href="javascript:' not in escaped
    assert "http://x/&lt;script&gt;" in escaped

    client = _client(tmp_path)
    denied = client.post("/admin/copy", data={"home_intro": "nope", "csrf": "nope"})
    assert denied.status_code == 403

    _sign_in(client)
    admin = client.get("/admin")
    assert admin.status_code == 200
    assert "Page text" in admin.text
    assert "Save page text" in admin.text
    token = _csrf(admin.text)
    custom = "Office copy <script>alert(1)</script> [bad](javascript:alert(1))"
    saved = client.post(
        "/admin/copy",
        data={**DEFAULTS, "csrf": token, "home_intro": custom, "install_intro": "Custom install line."},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert saved.headers["location"] == "/admin?saved=text"
    history = client.get("/releases")
    assert "Office copy" in history.text
    assert "<script>alert" not in history.text
    assert "&lt;script&gt;" in history.text
    assert 'href="javascript:' not in history.text
    install = client.get("/install")
    assert "Custom install line." in install.text
    assert "Open this page from the address" not in install.text

    admin = client.get(saved.headers["location"])
    assert "Saved the page text." in admin.text
    token = _csrf(admin.text)
    too_long = client.post(
        "/admin/copy",
        data={**DEFAULTS, "csrf": token, "home_intro": "x" * 20001},
    )
    assert too_long.status_code == 400
    assert "20000" in too_long.text
    assert "Office copy" in client.get("/releases").text

    admin = client.get("/admin")
    token = _csrf(admin.text)
    reset = client.post(
        "/admin/copy/reset",
        data={"csrf": token},
        follow_redirects=False,
    )
    assert reset.status_code == 303
    install = client.get("/install")
    assert "Open this page from the address" in install.text
    assert "Custom install line." not in install.text
    assert "Restored the original page text." in client.get(reset.headers["location"]).text


def test_source_run_keeps_data_in_the_working_directory(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("YAVER_RELEASE_DATA", raising=False)
    app = create_app()
    assert app.state.store.root == tmp_path / "data"


def test_relative_data_dir_stays_next_to_the_executable(tmp_path: Path, monkeypatch):
    exe_dir = tmp_path / "install"
    exe_dir.mkdir()
    monkeypatch.setattr("yaver_releases.paths.install_dir", lambda: exe_dir)
    monkeypatch.setenv("YAVER_RELEASE_DATA", "kept")
    app = create_app()
    assert app.state.store.root == exe_dir / "kept"


def test_absolute_data_dir_is_unchanged(tmp_path: Path, monkeypatch):
    other = tmp_path / "elsewhere"
    monkeypatch.setenv("YAVER_RELEASE_DATA", str(other))
    app = create_app()
    assert app.state.store.root == other


def test_dotenv_reads_the_file_next_to_the_executable(tmp_path: Path, monkeypatch):
    exe_dir = tmp_path / "install"
    exe_dir.mkdir()
    (exe_dir / ".env").write_text("YAVER_RELEASE_PORT=18091\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("YAVER_RELEASE_PORT", raising=False)
    monkeypatch.setattr("yaver_releases.paths.install_dir", lambda: exe_dir)
    load_dotenv()
    assert os.environ["YAVER_RELEASE_PORT"] == "18091"


_BUNDLE_NAMES = {
    "windows": "yaver-windows-x64-{version}.zip",
    "ubuntu-18.04": "yaver-linux-x64-ubuntu-18.04-{version}.zip",
    "ubuntu-20.04": "yaver-linux-x64-ubuntu-20.04-{version}.zip",
    "ubuntu-22.04": "yaver-linux-x64-ubuntu-22.04-{version}.zip",
    "ubuntu-24.04": "yaver-linux-x64-ubuntu-24.04-{version}.zip",
}


def _frozen_package(binary: str, version: str) -> bytes:
    return _zip({binary: "bin", "_internal/a": "x", "VERSION": version + "\n"})


def _executable_bundle(
    version: str = "0.9.79",
    *,
    skip: set[str] | None = None,
    versions: dict[str, str] | None = None,
    extra: dict[str, bytes] | None = None,
    wrap: str = "",
) -> bytes:
    files: dict[str, bytes] = {}
    for platform, pattern in _BUNDLE_NAMES.items():
        if skip and platform in skip:
            continue
        ver = (versions or {}).get(platform, version)
        name = pattern.format(version=ver)
        binary = "yaver.exe" if platform == "windows" else "yaver"
        files[f"{wrap}{name}"] = _frozen_package(binary, ver)
    if extra:
        for name, payload in extra.items():
            files[f"{wrap}{name}"] = payload
    return _zip_bytes(files)


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def test_home_lists_each_ubuntu_download(tmp_path: Path):
    client = _client(tmp_path)
    home = client.get("/")
    assert home.status_code == 200
    assert "<h2>Ubuntu 18.04</h2>" in home.text
    assert "<h2>Ubuntu 20.04</h2>" in home.text
    assert "<h2>Ubuntu 22.04</h2>" in home.text
    assert "<h2>Ubuntu 24.04</h2>" in home.text
    assert "<h2>Windows</h2>" in home.text
    install = client.get("/install")
    assert 'id="ubuntu-18.04"' in install.text
    assert "http://testserver/download/ubuntu-22.04" in install.text


def test_bundle_upload_reads_the_version_from_the_zip_names(tmp_path: Path):
    client = _client(tmp_path)
    _sign_in(client)
    admin = client.get("/admin")
    assert 'value="ubuntu-18.04"' not in admin.text
    assert 'name="kind" value="bundle"' in admin.text
    token = _csrf(admin.text)
    published = client.post(
        "/admin/upload",
        data={"kind": "bundle", "notes": "Office <b>build</b>", "csrf": token},
        files={
            "package": (
                "yaver-executables-0.9.79.zip",
                _executable_bundle(),
                "application/zip",
            )
        },
        follow_redirects=False,
    )
    assert published.status_code == 303
    assert published.headers["location"] == "/admin?uploaded=bundle"

    history = client.get("/releases")
    assert "0.9.79" in history.text
    assert "Office &lt;b&gt;build&lt;/b&gt;" in history.text
    assert 'href="/download/windows/0.9.79"' in history.text
    assert 'href="/download/ubuntu-18.04/0.9.79"' in history.text
    assert 'href="/download/ubuntu-20.04/0.9.79"' in history.text
    assert 'href="/download/ubuntu-22.04/0.9.79"' in history.text
    assert 'href="/download/ubuntu-24.04/0.9.79"' in history.text
    assert 'id="release-0.9.79"' in history.text

    windows = client.get("/api/latest?platform=windows").json()
    ubuntu = client.get("/api/latest?platform=ubuntu-22.04").json()
    assert windows["version"] == "0.9.79"
    assert ubuntu["version"] == "0.9.79"
    assert windows["filename"] == "yaver-windows-x64-0.9.79.zip"
    assert ubuntu["filename"] == "yaver-linux-x64-ubuntu-22.04-0.9.79.zip"
    assert windows["layout"] == "frozen"
    assert ubuntu["sha256"] != windows["sha256"]

    with zipfile.ZipFile(io.BytesIO(client.get("/download/windows").content)) as archive:
        assert archive.read("update.bat") == updater_bytes("update.bat")
        assert "yaver.exe" in archive.namelist()
    with zipfile.ZipFile(io.BytesIO(client.get("/download/ubuntu-24.04").content)) as archive:
        assert archive.read("update.sh") == updater_bytes("update.sh")
        assert (archive.getinfo("update.sh").external_attr >> 16) & 0o777 == 0o755
    assert client.get("/download/ubuntu-18.04").status_code == 200
    assert client.get("/download/ubuntu-20.04").status_code == 200

    admin = client.get(published.headers["location"])
    assert "Published the Windows, Ubuntu 18.04, Ubuntu 20.04, Ubuntu 22.04, and Ubuntu 24.04 packages." in admin.text
    assert "Ubuntu 22.04" in admin.text


def test_bundle_upload_reads_release_notes_txt(tmp_path: Path):
    client = _client(tmp_path)
    _sign_in(client)
    token = _csrf(client.get("/admin").text)
    note = (
        "# Yaver 0.9.79\n\n"
        "See <script>alert(1)</script> and `update.bat`.\n\n"
        "The second paragraph stays."
    )
    published = client.post(
        "/admin/upload",
        data={"kind": "bundle", "notes": "typed in the form", "csrf": token},
        files={
            "package": (
                "yaver-executables-0.9.79.zip",
                _executable_bundle(extra={"RELEASE_NOTES.txt": note.encode("utf-8")}),
                "application/zip",
            )
        },
        follow_redirects=False,
    )
    assert published.status_code == 303
    history = client.get("/releases")
    assert history.status_code == 200
    assert "typed in the form" not in history.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in history.text
    assert "<script>alert" not in history.text
    assert "<code>update.bat</code>" in history.text
    assert "The second paragraph stays." in history.text
    assert history.text.count("The second paragraph stays.") == 1
    assert 'class="release-note"' in history.text
    windows = client.get("/api/latest?platform=windows").json()
    ubuntu = client.get("/api/latest?platform=ubuntu-24.04").json()
    assert windows["notes"] == note.strip()
    assert ubuntu["notes"] == note.strip()

    token = _csrf(client.get("/admin").text)
    older = client.post(
        "/admin/upload",
        data={"kind": "bundle", "csrf": token},
        files={
            "package": (
                "yaver-executables-0.9.72.zip",
                _executable_bundle(
                    "0.9.72",
                    extra={"RELEASE_NOTES.txt": b"The 0.9.72 note.\n"},
                ),
                "application/zip",
            )
        },
        follow_redirects=False,
    )
    assert older.status_code == 303
    both = client.get("/releases").text
    assert "The second paragraph stays." in both
    assert "The 0.9.72 note." in both

    token = _csrf(client.get("/admin").text)
    empty = client.post(
        "/admin/upload",
        data={"kind": "bundle", "csrf": token},
        files={
            "package": (
                "yaver-executables-0.9.80.zip",
                _executable_bundle("0.9.80", extra={"RELEASE_NOTES.txt": b"  \n"}),
                "application/zip",
            )
        },
    )
    assert empty.status_code == 400
    assert "empty" in empty.text.lower()
    assert client.get("/api/latest?platform=windows").json()["version"] == "0.9.79"

    token = _csrf(client.get("/admin").text)
    binary = client.post(
        "/admin/upload",
        data={"kind": "bundle", "csrf": token},
        files={
            "package": (
                "yaver-executables-0.9.80.zip",
                _executable_bundle("0.9.80", extra={"RELEASE_NOTES.txt": b"\xff\xfe"}),
                "application/zip",
            )
        },
    )
    assert binary.status_code == 400
    assert "UTF-8" in binary.text

    token = _csrf(client.get("/admin").text)
    wrapped = client.post(
        "/admin/upload",
        data={"kind": "bundle", "csrf": token},
        files={
            "package": (
                "drop.zip",
                _executable_bundle(
                    "0.9.71",
                    extra={"RELEASE_NOTES.txt": "Wrapped note.\n".encode("utf-8")},
                    wrap="yaver-executables-0.9.71/",
                ),
                "application/zip",
            )
        },
        follow_redirects=False,
    )
    assert wrapped.status_code == 303
    assert "Wrapped note." in client.get("/releases").text

    token = _csrf(client.get("/admin").text)
    huge = client.post(
        "/admin/upload",
        data={"kind": "bundle", "csrf": token},
        files={
            "package": (
                "yaver-executables-0.9.81.zip",
                _executable_bundle("0.9.81", extra={"RELEASE_NOTES.txt": b"a" * 70000}),
                "application/zip",
            )
        },
    )
    assert huge.status_code == 400
    assert "too long" in huge.text.lower()
    assert client.get("/api/latest?platform=windows").json()["version"] == "0.9.79"


def test_bundle_upload_rejects_a_partial_set_and_keeps_the_old_file(tmp_path: Path):
    client = _client(tmp_path)
    _sign_in(client)
    token = _csrf(client.get("/admin").text)
    first = client.post(
        "/admin/upload",
        data={"platform": "windows", "version": "0.9.72", "csrf": token},
        files={
            "package": (
                "yaver-windows.zip",
                _zip({"yaver.exe": "old", "_internal/a": "x"}),
                "application/zip",
            )
        },
        follow_redirects=False,
    )
    assert first.status_code == 303
    previous = client.get("/download/windows").content

    token = _csrf(client.get("/admin").text)
    rejected = client.post(
        "/admin/upload",
        data={"kind": "bundle", "csrf": token},
        files={
            "package": (
                "yaver-executables-0.9.79.zip",
                _executable_bundle(skip={"ubuntu-20.04"}),
                "application/zip",
            )
        },
    )
    assert rejected.status_code == 400
    assert "Ubuntu 20.04" in rejected.text
    assert client.get("/download/windows").content == previous
    assert client.get("/api/latest?platform=ubuntu-18.04").status_code == 404
    assert len(list((tmp_path / "data" / "files").glob("*.zip"))) == 1


def test_bundle_upload_refuses_a_version_that_disagrees_with_the_name(tmp_path: Path):
    client = _client(tmp_path)
    _sign_in(client)
    token = _csrf(client.get("/admin").text)
    files = {}
    for platform, pattern in _BUNDLE_NAMES.items():
        binary = "yaver.exe" if platform == "windows" else "yaver"
        inside = "0.9.78" if platform == "windows" else "0.9.79"
        files[pattern.format(version="0.9.79")] = _frozen_package(binary, inside)
    rejected = client.post(
        "/admin/upload",
        data={"kind": "bundle", "csrf": token},
        files={"package": ("yaver-executables-0.9.79.zip", _zip_bytes(files), "application/zip")},
    )
    assert rejected.status_code == 400
    assert "0.9.78" in rejected.text
    assert client.get("/api/latest?platform=windows").status_code == 404
    assert client.get("/api/latest?platform=ubuntu-22.04").status_code == 404


def test_bundle_upload_accepts_one_wrapping_folder(tmp_path: Path):
    client = _client(tmp_path)
    _sign_in(client)
    token = _csrf(client.get("/admin").text)
    published = client.post(
        "/admin/upload",
        data={"kind": "bundle", "csrf": token},
        files={
            "package": (
                "drop.zip",
                _executable_bundle(wrap="yaver-executables-0.9.79/"),
                "application/zip",
            )
        },
        follow_redirects=False,
    )
    assert published.status_code == 303
    assert client.get("/api/latest?platform=ubuntu-18.04").json()["version"] == "0.9.79"


def test_bundle_upload_uses_the_file_name_when_version_is_absent(tmp_path: Path):
    client = _client(tmp_path)
    _sign_in(client)
    token = _csrf(client.get("/admin").text)
    files: dict[str, bytes] = {}
    for platform, pattern in _BUNDLE_NAMES.items():
        binary = "yaver.exe" if platform == "windows" else "yaver"
        files[pattern.format(version="0.9.79")] = _zip({binary: "bin", "_internal/a": "x"})
    published = client.post(
        "/admin/upload",
        data={"kind": "bundle", "csrf": token},
        files={"package": ("yaver-executables-0.9.79.zip", _zip_bytes(files), "application/zip")},
        follow_redirects=False,
    )
    assert published.status_code == 303
    assert client.get("/api/latest?platform=windows").json()["version"] == "0.9.79"
    assert client.get("/api/latest?platform=ubuntu-20.04").json()["version"] == "0.9.79"


def test_bundle_upload_rejects_an_extra_file_a_bad_outer_name_and_a_parent_path(tmp_path: Path):
    client = _client(tmp_path)
    _sign_in(client)
    token = _csrf(client.get("/admin").text)
    extra = client.post(
        "/admin/upload",
        data={"kind": "bundle", "csrf": token},
        files={
            "package": (
                "yaver-executables-0.9.79.zip",
                _executable_bundle(extra={"notes.txt": b"no"}),
                "application/zip",
            )
        },
    )
    assert extra.status_code == 400
    assert "five versioned" in extra.text
    assert client.get("/api/latest?platform=windows").status_code == 404

    token = _csrf(client.get("/admin").text)
    outer = client.post(
        "/admin/upload",
        data={"kind": "bundle", "csrf": token},
        files={
            "package": (
                "yaver-executables-0.9.80.zip",
                _executable_bundle("0.9.79"),
                "application/zip",
            )
        },
    )
    assert outer.status_code == 400
    assert "0.9.80" in outer.text
    assert "0.9.79" in outer.text

    token = _csrf(client.get("/admin").text)
    slipped = client.post(
        "/admin/upload",
        data={"kind": "bundle", "csrf": token},
        files={
            "package": (
                "yaver-executables-0.9.79.zip",
                _zip_bytes({"../yaver-windows-x64-0.9.79.zip": b"no"}),
                "application/zip",
            )
        },
    )
    assert slipped.status_code == 400
    assert "parent path" in slipped.text
    assert list((tmp_path / "data" / "files").glob("*.zip")) == []


def test_version_checks_are_listed_by_address_for_an_admin(tmp_path: Path):
    client = _client(tmp_path)
    assert client.get("/api/admin/installations").status_code == 403
    assert client.get("/admin/analytics", follow_redirects=False).status_code == 303
    assert 'href="/admin/analytics"' not in client.get("/").text

    first = client.get("/api/latest?platform=windows&current=0.9.81")
    assert first.status_code == 404
    client.get("/api/latest?platform=windows&current=<script>")
    client.get("/api/latest?platform=ubuntu-22.04&current=0.9.80")

    _sign_in(client)
    for public in ("/", "/install", "/releases", "/dependencies"):
        assert 'href="/admin/analytics"' not in client.get(public).text
    page = client.get("/admin/analytics")
    assert page.status_code == 200
    assert 'href="/admin/analytics"' in page.text
    assert ">Analytics<" in page.text
    assert 'aria-current="page"' in page.text
    publish = client.get("/admin")
    assert 'href="/admin/analytics"' in publish.text
    assert ">Analytics<" in publish.text
    assert "testclient" in page.text
    assert "0.9.80" in page.text
    assert "ubuntu-22.04" in page.text
    assert "Last contact" in page.text
    assert "&lt;script&gt;" not in page.text
    chosen = client.get("/admin/analytics?ip=testclient")
    assert chosen.status_code == 200
    assert "Version check" in chosen.text
    assert "ubuntu-22.04" in chosen.text
    assert "Version " in chosen.text
    assert "Platform " in chosen.text
    assert "Last contact " in chosen.text
    assert "This address is not an IP address." in chosen.text
    posted = client.post(
        "/api/latest",
        params={"platform": "windows", "current": "0.9.81"},
        json={"usage": {"jobs": 17, "merge_requests": 13}},
    )
    assert posted.status_code == 405

    body = client.get("/api/admin/installations?ip=testclient").json()
    assert len(body["installations"]) == 1
    row = body["installations"][0]
    assert row["ip"] == "testclient"
    assert row["hits"] == 3
    assert row["client_version"] == "0.9.80"
    assert row["platform"] == "ubuntu-22.04"
    assert body["selected"]["events"][0]["client_version"] == "0.9.80"
    assert all("<" not in event["client_version"] for event in body["selected"]["events"])
    assert "usage" not in row

    fresh = TestClient(client.app)
    opened = fresh.get("/api/admin/installations", auth=("admin", "correct-horse"))
    assert opened.status_code == 200
    assert opened.json()["installations"][0]["ip"] == "testclient"
    denied = fresh.get("/api/admin/installations", auth=("admin", "wrong"))
    assert denied.status_code == 403
    assert "www-authenticate" not in {key.lower() for key in denied.headers}
    assert body["selected"]["usage"] is None
    assert body["selected"]["usage_error"] == "This address is not an IP address."


class _InstallServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler]) -> None:
        super().__init__(address, handler)
        self.mode = "ok"
        self.seen: list[tuple[str, str, str]] = []


class _InstallHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        server = self.server
        if not isinstance(server, _InstallServer):
            self.send_error(500)
            return
        server.seen.append((self.command, self.path, self.headers.get("Authorization") or ""))
        if server.mode == "redirect":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:8080/api/analytics")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if server.mode == "huge":
            raw = b'{"jobs":999,"pad":"' + (b"x" * 70000) + b'"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        expected = f"Bearer {INSTALL_ANALYTICS_TOKEN}"
        presented = self.headers.get("Authorization") or ""
        if len(presented) != len(expected) or not hmac.compare_digest(presented, expected):
            raw = b'{"detail":"Forbidden"}'
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        payload = {
            "jobs": 17,
            "completed": 9,
            "error": 4,
            "cancelled": 2,
            "plan_ready": 1,
            "in_flight": 1,
            "merge_requests": 13,
            "opened": 3,
            "merged": 8,
            "closed": 2,
            "client_version": "0.0.1",
            "ours": {"opened": 2, "merged": 6, "closed": 1, "total": 9},
            "contributed": {"opened": 1, "merged": 2, "closed": 1, "total": 4},
            "categories": [
                {
                    "label": "Build",
                    "jobs": 11,
                    "completed": 8,
                    "error": 2,
                    "cancelled": 1,
                    "plan_ready": 0,
                    "in_flight": 0,
                }
            ],
            "models": [{"label": "opencode/deepseek <script>", "jobs": 17}],
            "agents": [{"label": "derman-build", "jobs": 11}],
            "repositories": [{"label": "https://gitlab.example/group/app", "jobs": 11}],
            "statuses": [{"label": "completed", "jobs": 9}],
        }
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def _remember(client: TestClient, ip: str, *, platform: str = "windows", version: str = "0.9.81") -> None:
    client.app.state.store.record_install_hit(
        ip=ip,
        kind="latest",
        platform=platform,
        client_version=version,
        published_version="0.9.81",
    )


def test_selecting_an_address_gets_that_installs_analytics(tmp_path: Path, monkeypatch):
    server = _InstallServer(("127.0.0.1", 0), _InstallHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    assert port != 8080
    monkeypatch.setattr("yaver_releases.install_fetch.INSTALL_ANALYTICS_PORT", port)
    client = _client(tmp_path)
    _remember(client, "127.0.0.1")
    _remember(client, "evil.test")
    _remember(client, "169.254.169.254")
    try:
        assert client.get("/admin/analytics?ip=127.0.0.1", follow_redirects=False).status_code == 303
        assert server.seen == []
        _sign_in(client)
        assert client.get("/admin/analytics").status_code == 200
        assert server.seen == []
        missing = client.get("/admin/analytics?ip=10.9.8.7")
        assert missing.status_code == 200
        assert "No requests from 10.9.8.7" in missing.text
        assert server.seen == []

        page = client.get("/admin/analytics?ip=127.0.0.1")
        assert page.status_code == 200
        assert len(server.seen) == 1
        method, path, authorization = server.seen[0]
        assert method == "GET"
        assert path == "/api/analytics/install"
        assert authorization == f"Bearer {INSTALL_ANALYTICS_TOKEN}"
        assert "Version 0.9.81" in page.text
        assert "Platform windows" in page.text
        assert "Last contact " in page.text
        assert "Version 0.0.1" not in page.text
        assert ">17<" in page.text
        assert ">13<" in page.text
        assert "Opened by us" in page.text
        assert "Contributed" in page.text
        assert ">Build<" in page.text
        assert "derman-build" in page.text
        assert "gitlab.example/group/app" in page.text
        assert "opencode/deepseek script" in page.text
        assert "opencode/deepseek <script>" not in page.text
        assert INSTALL_ANALYTICS_TOKEN not in page.text

        body = client.get("/api/admin/installations?ip=127.0.0.1").json()
        assert body["selected"]["usage"]["jobs"] == 17
        assert body["selected"]["usage"]["merge_requests"] == 13
        assert body["selected"]["client_version"] == "0.9.81"
        assert body["selected"]["platform"] == "windows"
        assert body["selected"]["usage_error"] == ""
        assert "<" not in body["selected"]["usage"]["models"][0]["label"]
        assert "usage" not in body["installations"][0]
        assert INSTALL_ANALYTICS_TOKEN not in json.dumps(body)

        before = len(server.seen)
        client.get("/admin/analytics?ip=evil.test")
        client.get("/admin/analytics?ip=169.254.169.254")
        assert len(server.seen) == before

        server.mode = "redirect"
        redirected = client.get("/admin/analytics?ip=127.0.0.1")
        assert "redirected the analytics request" in redirected.text
        assert ">17<" not in redirected.text
        assert all(item[1] == "/api/analytics/install" for item in server.seen)

        server.mode = "huge"
        huge = client.get("/admin/analytics?ip=127.0.0.1")
        assert "too large" in huge.text
        assert ">999<" not in huge.text
    finally:
        server.shutdown()
        server.server_close()


def test_dependencies_require_the_network_certificate_first(tmp_path: Path):
    client = _client(tmp_path)
    page = client.get("/dependencies")
    assert page.status_code == 200
    text = page.text
    head = text[:text.index('id="opencode"')]
    assert "Before anything else" in head
    assert "NODE_EXTRA_CA_CERTS" in head
    assert "system variable" in head
    assert "external link in the description" in head
    assert 'href="/static/network-ca.crt"' not in text
    assert "/static/network-ca.crt" not in text
    assert 'class="button"' not in head
    assert head.count('<a href="#deps-intro">Download it</a>') == 2
    windows_h = head.index("<h3>Windows</h3>")
    linux_h = head.index("<h3>Linux</h3>")
    first_link = head.index('<a href="#deps-intro">Download it</a>')
    assert windows_h < first_link < linux_h
    assert "C:\\certs\\network-ca.crt" in head
    assert "~/certs/network-ca.crt" in head
    assert "NODE_EXTRA_CA_CERTS=$HOME/certs/network-ca.crt" in head
    assert "NODE_EXTRA_CA_CERTS=/certs/network-ca.crt" not in head
    assert "New-Item -ItemType Directory -Force -Path C:\\certs" not in head
    assert "mkdir -p /certs" not in head
    assert '"Machine"' in head
    assert "/etc/environment" in head
    assert head.index("<h3>Windows</h3>") < head.index("<h3>Linux</h3>")
    assert head.index("NODE_EXTRA_CA_CERTS") < head.index("<h3>Windows</h3>")
    assert "NODE_EXTRA_CA_CERTS" not in client.get("/install").text
    assert "PRIVATE KEY" not in head


def test_certificate_address_is_the_external_link_in_the_description(tmp_path: Path):
    from yaver_releases.copy import DEFAULTS, certificate_url

    assert certificate_url("see [cert](https://certs.example/a.crt) later") == "https://certs.example/a.crt"
    assert certificate_url("plain https://certs.example/plain.crt end") == "https://certs.example/plain.crt"
    assert certificate_url("[x](javascript:alert(1))") == ""
    assert certificate_url('[x](https://certs.example/a"b)') == ""
    assert certificate_url("[local](/static/network-ca.crt)") == ""

    client = _client(tmp_path)
    _sign_in(client)
    admin = client.get("/admin")
    token = _csrf(admin.text)
    intro = DEFAULTS["deps_intro"] + " [Download certificate](https://certs.example/network-ca.crt)"
    saved = client.post(
        "/admin/copy",
        data={**DEFAULTS, "csrf": token, "deps_intro": intro},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    page = client.get("/dependencies")
    text = page.text
    head = text[:text.index('id="opencode"')]
    assert head.count('href="https://certs.example/network-ca.crt"') == 3
    assert head.count("https://certs.example/network-ca.crt") == 3
    assert 'class="button"' not in head
    assert "/static/network-ca.crt" not in text
    assert "New-Item -ItemType Directory -Force -Path C:\\certs" not in head
    assert "mkdir -p /certs" not in head
    assert "curl.exe -fL -o C:\\certs\\network-ca.crt" not in head
    assert "sudo curl -fL -o /certs/network-ca.crt" not in head

    admin = client.get("/admin")
    token = _csrf(admin.text)
    rejected = client.post(
        "/admin/copy",
        data={**DEFAULTS, "csrf": token, "deps_intro": "Only [bad](javascript:alert(1))."},
        follow_redirects=False,
    )
    assert rejected.status_code == 303
    again = client.get("/dependencies").text
    cert = again[:again.index('id="opencode"')]
    assert 'href="javascript:' not in cert
    assert cert.count('<a href="#deps-intro">Download it</a>') == 2
    assert 'class="button"' not in cert
    assert "curl.exe -fL" not in cert


def test_opencode_warns_to_clear_the_config_folder(tmp_path: Path):
    client = _client(tmp_path)
    page = client.get("/dependencies")
    text = page.text
    opencode = text[text.index('id="opencode"'):text.index('id="claude"')]
    claude = text[text.index('id="claude"'):text.index('id="codex"')]
    assert "<strong>Warning</strong>:" in opencode
    assert "Remove anything that already exists under the user's" in opencode
    assert ".config/opencode" in opencode
    assert "%USERPROFILE%\\.config\\opencode" in opencode
    assert "~/.config/opencode" in opencode
    assert "Config and agent files are kept in that folder." in opencode
    assert opencode.index("./install-opencode.sh") < opencode.index("<strong>Warning</strong>:")
    assert opencode.index("<strong>Warning</strong>:") < opencode.index("sample-config")
    assert "<strong>Warning</strong>:" not in claude
    assert "<strong>Warning</strong>:" not in text[text.index('id="codex"'):]
    assert client.get("/install").text.count("<strong>Warning</strong>:") == 5


def test_each_dependency_has_a_sample_config_to_copy(tmp_path: Path):
    client = _client(tmp_path)
    page = client.get("/dependencies")
    assert page.status_code == 200
    text = page.text
    assert text.count('class="sample-config"') == 3
    assert text.count('data-copy-target="sample-') == 3
    for tool, filename, windows_dest, linux_dest, marker in (
        (
            "opencode",
            "opencode.json",
            r"%USERPROFILE%\.opencode\opencode.json",
            "~/.opencode/opencode.json",
            '"baseURL": "https://YOUR_HOST/v1"',
        ),
        (
            "claude",
            "settings.json",
            r"%USERPROFILE%\.claude\settings.json",
            "~/.claude/settings.json",
            '"ANTHROPIC_BASE_URL": "https://YOUR_HOST"',
        ),
        (
            "codex",
            "config.toml",
            r"%USERPROFILE%\.codex\config.toml",
            "~/.codex/config.toml",
            'base_url = "https://YOUR_HOST/v1"',
        ),
    ):
        assert f'id="sample-{tool}"' in text
        assert f'for="sample-{tool}"' in text
        assert f'data-copy-target="sample-{tool}"' in text
        start = text.index(f'id="{tool}"')
        fold = text[start:text.index("</details>", start)]
        assert filename in fold
        windows = fold[:fold.index("<h3>Linux</h3>")]
        linux = fold[fold.index("<h3>Linux</h3>"):fold.index(f'for="sample-{tool}"')]
        label = fold[fold.index(f'for="sample-{tool}"'):fold.index("sample-config")]
        assert f"<code>{filename}</code> to <code>{windows_dest}</code>" in windows
        assert f"<code>{filename}</code> to <code>{linux_dest}</code>" in linux
        assert windows_dest in label
        assert linux_dest in label
        assert fold.index(f"./install-{tool}.sh") < fold.index("sample-config")
        assert fold.index("<h3>Linux</h3>") < fold.index("sample-config")
        assert marker in html_lib.unescape(fold)
    assert "YOUR_TOKEN" in text
    assert "YOUR_MODEL" in text
    assert "CUSTOM_HOST_TOKEN" in text
    assert 'class="sample-config"' not in client.get("/install").text
    script = client.get("/static/theme.js")
    assert script.status_code == 200
    assert "data-copy-target" in script.text
    assert "execCommand" in script.text
    assert "innerHTML" not in script.text


def test_edge_keeps_the_night_and_light_switch(tmp_path: Path):
    """Edge drops the "only" keyword from the colorScheme property and then
    repaints the page with its own colors. The served page has to opt out
    before the stylesheet, and the click handler has to keep that keyword.
    """
    client = _client(tmp_path)
    page = client.get("/install")
    assert page.status_code == 200
    assert page.headers["x-ua-compatible"] == "IE=edge"
    html = page.text
    assert 'data-theme="dark"' in html
    assert 'style="color-scheme: only dark"' in html
    assert '<meta name="color-scheme" content="only dark">' in html
    assert 'root.style.setProperty("color-scheme", scheme)' in html
    assert "only light" in html
    assert ".colorScheme" not in html
    assert html.index('name="color-scheme"') < html.index('href="/static/site.css"')
    assert html.index('setProperty("color-scheme"') < html.index('href="/static/site.css"')
    assert html.index('http-equiv="X-UA-Compatible"') < html.index("<title>")

    css = client.get("/static/site.css")
    assert css.status_code == 200
    assert css.headers["x-ua-compatible"] == "IE=edge"
    assert "color-scheme: only dark" in css.text
    assert "color-scheme: only light" in css.text
    assert "background-attachment" not in css.text
    assert "body::before" in css.text
    assert "html[data-theme=\"light\"] body" in css.text

    script = client.get("/static/theme.js")
    assert script.status_code == 200
    assert 'root.style.setProperty("color-scheme", scheme)' in script.text
    assert "only light" in script.text
    assert "only dark" in script.text
    assert ".colorScheme" not in script.text
    assert 'localStorage.setItem(key, next)' in script.text
