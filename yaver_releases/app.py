"""Public release pages, the admin upload, and the API Yaver calls."""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from yaver_releases.auth import (
    COOKIE,
    csrf_ok,
    load_secret,
    new_csrf,
    passwords_match,
    read_csrf,
    read_session,
    sign_csrf,
    sign_session,
)
from yaver_releases.copy import (
    SECTIONS,
    TOKEN_HELP,
    CopyError,
    clean_body,
    public_html,
    sections_for_edit,
    tokens_from_url,
)
from yaver_releases.platforms import (
    DEPENDENCIES,
    PLATFORMS,
    PackageError,
    flatten_wrapper,
    inspect_zip,
    package_label,
    require_version,
    safe_filename,
    version_from_zip,
)
from yaver_releases.store import ReleaseStore

_ROOT = Path(__file__).resolve().parent
_TEMPLATES = Jinja2Templates(directory=str(_ROOT / "templates"))


def _format_size(value: object) -> str:
    try:
        size = int(value or 0)
    except (TypeError, ValueError):
        size = 0
    number = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if number < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(number)} {unit}"
            return f"{number:.1f} {unit}"
        number /= 1024
    return f"{size} B"


def _layout_label(value: object) -> str:
    return {
        "frozen": "Executable",
        "source": "Install zip",
        "cli": "Command-line tool",
        "unknown": "Unrecognized",
    }.get(str(value or ""), "")


_TEMPLATES.env.filters["size"] = _format_size
_TEMPLATES.env.filters["layout_label"] = _layout_label
_MAX_UPLOAD = 8 * 1024 * 1024 * 1024
_FAILS: dict[str, list[float]] = {}


def create_app(
    *,
    data_dir: Path | None = None,
    admin_user: str | None = None,
    admin_password: str | None = None,
    secret: str | None = None,
) -> FastAPI:
    root = Path(data_dir or os.environ.get("YAVER_RELEASE_DATA") or "data")
    root.mkdir(parents=True, exist_ok=True)
    store = ReleaseStore(root)
    user = admin_user if admin_user is not None else os.environ.get("YAVER_RELEASE_ADMIN_USER", "")
    password = (
        admin_password
        if admin_password is not None
        else os.environ.get("YAVER_RELEASE_ADMIN_PASSWORD", "")
    )
    user = (user or "").strip()
    password = password or ""
    signing = load_secret(root, secret if secret is not None else os.environ.get("YAVER_RELEASE_SECRET"))

    app = FastAPI(title="Yaver releases", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.state.admin_user = user
    app.state.admin_password = password
    app.state.secret = signing
    app.mount("/static", StaticFiles(directory=str(_ROOT / "static")), name="static")

    @app.middleware("http")
    async def _headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/releases")
    def releases() -> dict:
        return {
            "releases": store.list_all(),
            "dependencies": store.list_dependencies(),
        }

    @app.get("/api/latest")
    def latest(platform: str = "") -> dict:
        key = _platform_or_404(platform)
        row = store.get(key)
        if row is None or not row.get("version"):
            raise HTTPException(status_code=404, detail=f"No {PLATFORMS[key]} release is published.")
        return row

    @app.get("/download/{platform}")
    def download(platform: str) -> FileResponse:
        key = _package_or_404(platform)
        row = store.get(key)
        path = store.blob_path(key)
        if row is None or path is None:
            raise HTTPException(
                status_code=404,
                detail=f"No {package_label(key)} release is published.",
            )
        return FileResponse(
            path,
            media_type="application/zip",
            filename=row["filename"],
            content_disposition_type="attachment",
        )

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request,
            "home.html",
            _public_context(request, store),
        )

    @app.get("/install", response_class=HTMLResponse)
    def install(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request,
            "install.html",
            _public_context(request, store),
        )

    @app.get("/admin/login", response_class=HTMLResponse)
    def login_form(request: Request) -> HTMLResponse:
        return _login_page(request, app, "")

    @app.post("/admin/login")
    def login(request: Request, username: str = Form(""), password: str = Form(""), csrf: str = Form("")):
        if not _csrf_matches(request, app, csrf):
            return _login_page(request, app, "The form expired. Try again.")
        if not app.state.admin_user or not app.state.admin_password:
            return _login_page(
                request,
                app,
                "Set YAVER_RELEASE_ADMIN_USER and YAVER_RELEASE_ADMIN_PASSWORD, then start the server again.",
            )
        ip = request.client.host if request.client else ""
        if _locked_out(ip):
            return _login_page(request, app, "Too many tries. Wait a few minutes.")
        user_ok = passwords_match(app.state.admin_user, username)
        password_ok = passwords_match(app.state.admin_password, password)
        if not user_ok or not password_ok:
            _note_failure(ip)
            time.sleep(0.4)
            return _login_page(request, app, "Wrong username or password.")
        _clear_failures(ip)
        token_csrf = new_csrf()
        response = RedirectResponse("/admin", status_code=303)
        response.set_cookie(
            COOKIE,
            sign_session(app.state.secret, user=app.state.admin_user, csrf=token_csrf),
            httponly=True,
            samesite="lax",
            path="/",
            max_age=12 * 60 * 60,
        )
        return response

    @app.post("/admin/logout")
    def logout(request: Request, csrf: str = Form("")):
        _require_admin(request, app, csrf)
        response = RedirectResponse("/admin/login", status_code=303)
        response.delete_cookie(COOKIE, path="/")
        return response

    @app.get("/admin", response_class=HTMLResponse)
    def admin(request: Request, uploaded: str = "", saved: str = "") -> HTMLResponse:
        session = _session_or_redirect(request, app)
        if isinstance(session, RedirectResponse):
            return session
        return _admin_page(request, app, session, _notice_for(uploaded, saved), "")

    @app.post("/admin/upload", response_class=HTMLResponse)
    def upload(
        request: Request,
        platform: str = Form(""),
        version: str = Form(""),
        notes: str = Form(""),
        csrf: str = Form(""),
        package: UploadFile = File(...),
    ):
        session = _require_admin(request, app, csrf)
        try:
            key = _package_or_404(platform)
            typed = require_version(version) if (version or "").strip() else ""
            filename = safe_filename(package.filename or "")
            note = _clean_notes(notes)
        except (PackageError, HTTPException) as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            return _admin_again(request, app, session, str(detail))
        blob = root / "incoming.tmp"
        size = 0
        try:
            with blob.open("wb") as handle:
                while True:
                    chunk = package.file.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > _MAX_UPLOAD:
                        raise PackageError("The zip is larger than 8 GB.")
                    handle.write(chunk)
            magic = blob.read_bytes()[:4]
            if magic not in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
                raise PackageError("The file is not a zip.")
            flatten_wrapper(blob)
            layout = inspect_zip(blob)
            inside = version_from_zip(blob)
            if inside and typed and inside != typed:
                raise PackageError(f"The VERSION file says {inside}.")
            ver = inside or typed
            if not ver:
                raise PackageError(
                    "Type a version, or put a VERSION file at the top of the zip."
                )
            digest = hashlib.sha256()
            published_size = 0
            with blob.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    published_size += len(chunk)
                    digest.update(chunk)
            store.publish(
                platform=key,
                version=ver,
                filename=filename,
                sha256=digest.hexdigest(),
                size=published_size,
                layout=layout,
                notes=note,
                blob=blob,
            )
        except PackageError as exc:
            return _admin_again(request, app, session, str(exc))
        finally:
            try:
                blob.unlink()
            except OSError:
                pass
        return RedirectResponse(f"/admin?uploaded={key}", status_code=303)

    @app.post("/admin/delete")
    def delete(request: Request, platform: str = Form(""), csrf: str = Form("")):
        _require_admin(request, app, csrf)
        key = _package_or_404(platform)
        store.delete(key)
        return RedirectResponse("/admin", status_code=303)

    @app.post("/admin/copy", response_class=HTMLResponse)
    async def save_page_copy(request: Request):
        form = await request.form()
        csrf = str(form.get("csrf") or "")
        session = _require_admin(request, app, csrf)
        drafts = {key: str(form.get(key) or "") for key, _label, _page in SECTIONS}
        try:
            cleaned = {key: clean_body(drafts[key]) for key, _label, _page in SECTIONS}
        except CopyError as exc:
            return _admin_page(request, app, session, "", str(exc), drafts=drafts, status_code=400)
        store.save_copy(cleaned)
        return RedirectResponse("/admin?saved=text", status_code=303)

    @app.post("/admin/copy/reset")
    def reset_page_copy(request: Request, csrf: str = Form("")):
        _require_admin(request, app, csrf)
        store.clear_copy()
        return RedirectResponse("/admin?saved=reset", status_code=303)

    return app


def _platform_or_404(value: str) -> str:
    """Yaver update targets only. A CLI id is not a platform."""
    key = (value or "").strip().lower()
    if key not in PLATFORMS:
        raise HTTPException(status_code=404, detail="Unknown platform.")
    return key


def _package_or_404(value: str) -> str:
    key = (value or "").strip().lower()
    if key not in PLATFORMS and key not in DEPENDENCIES:
        raise HTTPException(status_code=404, detail="Unknown platform.")
    return key


def _clean_notes(value: str) -> str:
    text = (value or "").replace("\x00", "").strip()
    if len(text) > 8000:
        raise PackageError("Notes must be 8000 characters or fewer.")
    return text


def _client_token(request: Request) -> str:
    return request.cookies.get(COOKIE) or ""


def _session(request: Request, app: FastAPI) -> dict | None:
    return read_session(app.state.secret, _client_token(request))


def _csrf_matches(request: Request, app: FastAPI, given: str) -> bool:
    # Login has no admin session yet. The hidden field must match the cookie
    # issued on GET /admin/login. A missing cookie fails closed.
    token = request.cookies.get("yaver_release_csrf") or ""
    data = read_csrf(app.state.secret, token)
    if not data:
        return False
    return csrf_ok(str(data.get("csrf") or ""), given)


def _require_admin(request: Request, app: FastAPI, csrf: str) -> dict:
    session = _session(request, app)
    if session is None or not csrf_ok(str(session.get("csrf") or ""), csrf):
        raise HTTPException(status_code=403, detail="Sign in again.")
    return session


def _session_or_redirect(request: Request, app: FastAPI) -> dict | RedirectResponse:
    session = _session(request, app)
    if session is None:
        return RedirectResponse("/admin/login", status_code=303)
    return session


def _login_page(request: Request, app: FastAPI, error: str) -> HTMLResponse:
    csrf = new_csrf()
    body = _TEMPLATES.TemplateResponse(
        request,
        "login.html",
        {
            "error": error,
            "configured": bool(app.state.admin_user and app.state.admin_password),
            "csrf": csrf,
        },
        status_code=400 if error else 200,
    )
    body.set_cookie(
        "yaver_release_csrf",
        sign_csrf(app.state.secret, csrf=csrf),
        httponly=True,
        samesite="lax",
        path="/admin",
        max_age=30 * 60,
    )
    return body


def _notice_for(uploaded: str, saved: str) -> str:
    if uploaded in PLATFORMS or uploaded in DEPENDENCIES:
        return f"Published the {package_label(uploaded)} package."
    if saved == "text":
        return "Saved the page text."
    if saved == "reset":
        return "Restored the original page text."
    return ""


def _dependency_groups() -> list[dict]:
    specs = (
        ("opencode", "OpenCode", "opencode_windows", "opencode_linux"),
        ("claude", "Claude Code", "claude_windows", "claude_linux"),
        ("codex", "Codex", "codex_windows", "codex_linux"),
    )
    return [
        {
            "id": tool,
            "label": label,
            "windows_copy": windows_copy,
            "linux_copy": linux_copy,
        }
        for tool, label, windows_copy, linux_copy in specs
    ]


def _public_context(request: Request, store: ReleaseStore) -> dict:
    return {
        "releases": store.list_all(),
        "dependency_rows": store.list_dependencies(),
        "dependencies": _dependency_groups(),
        "sections": _public_sections(request, store),
    }


def _public_sections(request: Request, store: ReleaseStore):
    tokens = tokens_from_url(
        str(request.base_url),
        request.url.hostname or "",
        request.url.port,
        request.url.scheme,
    )
    return public_html(store.copy_map(), tokens)


def _admin_page(
    request: Request,
    app: FastAPI,
    session: dict,
    notice: str,
    error: str,
    *,
    drafts: dict[str, str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return _TEMPLATES.TemplateResponse(
        request,
        "admin.html",
        {
            "releases": app.state.store.list_all(),
            "dependency_rows": app.state.store.list_dependencies(),
            "platforms": PLATFORMS,
            "dependency_platforms": DEPENDENCIES,
            "csrf": session["csrf"],
            "notice": notice,
            "error": error,
            "sections": sections_for_edit(app.state.store.copy_map(), drafts),
            "token_help": TOKEN_HELP,
        },
        status_code=status_code,
    )


def _admin_again(request: Request, app: FastAPI, session: dict, error: str) -> HTMLResponse:
    return _admin_page(request, app, session, "", error, status_code=400)


def _locked_out(ip: str) -> bool:
    now = time.time()
    recent = [stamp for stamp in _FAILS.get(ip, []) if now - stamp < 300]
    _FAILS[ip] = recent
    return len(recent) >= 8


def _note_failure(ip: str) -> None:
    _FAILS.setdefault(ip, []).append(time.time())


def _clear_failures(ip: str) -> None:
    _FAILS.pop(ip, None)
