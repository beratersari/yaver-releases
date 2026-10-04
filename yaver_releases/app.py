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
from yaver_releases.platforms import (
    PLATFORMS,
    PackageError,
    inspect_zip,
    require_version,
    safe_filename,
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
        return {"releases": store.list_all()}

    @app.get("/api/latest")
    def latest(platform: str = "") -> dict:
        key = _platform_or_404(platform)
        row = store.get(key)
        if row is None or not row.get("version"):
            raise HTTPException(status_code=404, detail=f"No {PLATFORMS[key]} release is published.")
        return row

    @app.get("/download/{platform}")
    def download(platform: str) -> FileResponse:
        key = _platform_or_404(platform)
        row = store.get(key)
        path = store.blob_path(key)
        if row is None or path is None:
            raise HTTPException(status_code=404, detail=f"No {PLATFORMS[key]} release is published.")
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
            {"releases": store.list_all()},
        )

    @app.get("/install", response_class=HTMLResponse)
    def install(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request,
            "install.html",
            {"releases": store.list_all()},
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
    def admin(request: Request, uploaded: str = "") -> HTMLResponse:
        session = _session_or_redirect(request, app)
        if isinstance(session, RedirectResponse):
            return session
        notice = ""
        if uploaded in PLATFORMS:
            notice = f"Published the {PLATFORMS[uploaded]} package."
        return _TEMPLATES.TemplateResponse(
            request,
            "admin.html",
            {
                "releases": store.list_all(),
                "platforms": PLATFORMS,
                "csrf": session["csrf"],
                "notice": notice,
                "error": "",
            },
        )

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
            key = _platform_or_404(platform)
            ver = require_version(version)
            filename = safe_filename(package.filename or "")
            note = _clean_notes(notes)
        except (PackageError, HTTPException) as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            return _admin_again(request, app, session, str(detail))
        blob = root / "incoming.tmp"
        digest = hashlib.sha256()
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
                    digest.update(chunk)
                    handle.write(chunk)
            magic = blob.read_bytes()[:4]
            if magic not in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
                raise PackageError("The file is not a zip.")
            layout = inspect_zip(blob)
            store.publish(
                platform=key,
                version=ver,
                filename=filename,
                sha256=digest.hexdigest(),
                size=size,
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
        key = _platform_or_404(platform)
        store.delete(key)
        return RedirectResponse("/admin", status_code=303)

    return app


def _platform_or_404(value: str) -> str:
    key = (value or "").strip().lower()
    if key not in PLATFORMS:
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


def _admin_again(request: Request, app: FastAPI, session: dict, error: str) -> HTMLResponse:
    return _TEMPLATES.TemplateResponse(
        request,
        "admin.html",
        {
            "releases": app.state.store.list_all(),
            "platforms": PLATFORMS,
            "csrf": session["csrf"],
            "notice": "",
            "error": error,
        },
        status_code=400,
    )


def _locked_out(ip: str) -> bool:
    now = time.time()
    recent = [stamp for stamp in _FAILS.get(ip, []) if now - stamp < 300]
    _FAILS[ip] = recent
    return len(recent) >= 8


def _note_failure(ip: str) -> None:
    _FAILS.setdefault(ip, []).append(time.time())


def _clear_failures(ip: str) -> None:
    _FAILS.pop(ip, None)
