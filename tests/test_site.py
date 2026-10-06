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
    assert "Install zip" not in install.text
    assert "cannot reach this IP" not in install.text
    assert "Run this site" not in install.text
    assert "install-dashboard" not in install.text
    assert "Settings, then Runtime" not in install.text
    assert "http://testserver/download/windows" in install.text
    assert "http://testserver/download/ubuntu-22.04" in install.text
    assert "curl.exe -fL" in install.text
    assert "tar.exe -xf yaver-windows.zip -C yaver" in install.text
    assert install.text.count("<details") == 8
    assert 'id="opencode"' in install.text
    assert 'id="claude"' in install.text
    assert 'id="codex"' in install.text
    assert install.text.index('id="ubuntu-24.04"') < install.text.index('id="opencode"')
    assert install.text.index('id="opencode"') < install.text.index('id="claude"')
    assert install.text.index('id="claude"') < install.text.index('id="codex"')
    assert "http://testserver/download/opencode-windows" in install.text
    assert "http://testserver/download/opencode-linux" in install.text
    assert "http://testserver/download/claude-windows" in install.text
    assert "http://testserver/download/claude-linux" in install.text
    assert "http://testserver/download/codex-windows" in install.text
    assert "http://testserver/download/codex-linux" in install.text
    assert ".\\install-opencode.bat" in install.text
    assert "./install-opencode.sh" in install.text
    assert ".\\install-claude.bat" in install.text
    assert "./install-claude.sh" in install.text
    assert ".\\install-codex.bat" in install.text
    assert "./install-codex.sh" in install.text
    assert "OpenCode for Windows" in home.text
    assert "Claude Code for Linux" in home.text
    assert "Codex for Windows" in home.text
    assert "install-opencode.bat" not in home.text
    assert "install-claude.sh" not in home.text
    assert "install-codex.bat" not in home.text
    assert "/download/opencode-windows" not in home.text
    assert "<details" not in home.text
    assert "Windows package is not published yet." not in home.text
    assert "Windows package is not published yet." not in install.text
    assert install.text.count("<h3>Windows</h3>") == 3
    assert install.text.count("<h3>Linux</h3>") == 3
    assert install.text.count("<h3>Install</h3>") == 5
    assert install.text.count("<h3>Update</h3>") == 5
    assert install.text.count("setsid nohup ./yaver start") == 4
    assert install.text.count("nano .env") == 5
    assert "notepad .env" in install.text
    assert install.text.count("./yaver update") == 4
    windows_at = install.text.index('id="windows"')
    windows_update = install.text.index(".\\yaver.exe update")
    ubuntu18 = install.text.index('id="ubuntu-18.04"')
    ubuntu22 = install.text.index('id="ubuntu-22.04"')
    ubuntu24 = install.text.index('id="ubuntu-24.04"')
    assert windows_at < windows_update < ubuntu18 < ubuntu22 < ubuntu24
    ubuntu22_block = install.text[ubuntu22:ubuntu24]
    assert "unzip -o /tmp/yaver-22.04.zip" in ubuntu22_block
    assert "nano .env" in ubuntu22_block
    assert "./yaver update" in ubuntu22_block
    assert "yaver-18.04.zip" not in ubuntu22_block
    assert "Start again later" not in install.text
    assert "Start-Process" not in install.text
    assert "&lt; /dev/null" in install.text
    assert "< /dev/null" not in install.text
    assert "unzip -o /tmp/yaver-22.04.zip" in install.text
    assert ".\\yaver.exe update" in install.text
    assert "./yaver update" in install.text
    assert "--host" not in install.text
    assert "--port" not in install.text
    assert "Copy-Item .env.example .env" in install.text
    assert "Update from Settings" not in home.text
    assert "yaver update" in home.text


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
    home = client.get("/")
    assert "1.18.10" in home.text
    assert "Command-line tool" in home.text
    assert 'href="/download/opencode-windows"' in home.text
    assert "install-opencode.bat" not in home.text
    install = client.get("/install")
    assert ".\\install-opencode.bat" in install.text
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
    home = client.get("/")
    assert "Office copy" in home.text
    assert "<script>alert" not in home.text
    assert "&lt;script&gt;" in home.text
    assert 'href="javascript:' not in home.text
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
    assert "Office copy" in client.get("/").text

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
