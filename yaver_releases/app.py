"""Public release pages, the admin upload, and the API Yaver calls."""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import shutil
import tempfile
import time
import zipfile
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
    CONFIG_DESTINATIONS,
    DEFAULTS,
    SAMPLE_CONFIGS,
    SECTIONS,
    TOKEN_HELP,
    CopyError,
    certificate_url,
    clean_body,
    public_html,
    render_copy,
    sections_for_edit,
    tokens_from_url,
)
from yaver_releases import paths
from yaver_releases.static_types import media_type_for
from yaver_releases.platforms import (
    DEPENDENCIES,
    PLATFORMS,
    PackageError,
    ensure_updater,
    flatten_wrapper,
    inspect_zip,
    is_executable_bundle,
    package_label,
    require_version,
    safe_filename,
    split_executable_bundle,
    version_from_zip,
)
from yaver_releases.install_fetch import fetch_install_analytics
from yaver_releases.store import ReleaseStore

_ROOT = Path(__file__).resolve().parent


def _template_context(request: Request) -> dict[str, bool]:
    """Analytics stays on the admin pages, and only for a signed-in admin."""
    app = request.app
    secret = getattr(app.state, "secret", "")
    signed = read_session(secret, request.cookies.get(COOKIE) or "") is not None
    path = (request.url.path or "/").rstrip("/") or "/"
    on_admin = path == "/admin" or path.startswith("/admin/analytics")
    return {"show_analytics_nav": signed and on_admin}


_TEMPLATES = Jinja2Templates(
    directory=str(_ROOT / "templates"),
    context_processors=[_template_context],
)
_LOG = logging.getLogger("yaver_releases")
_CLIENT_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,63}$")


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


def _release_note(value: object):
    return render_copy(str(value or ""))


_TEMPLATES.env.filters["size"] = _format_size
_TEMPLATES.env.filters["layout_label"] = _layout_label
_TEMPLATES.env.filters["release_note"] = _release_note
_MAX_UPLOAD = 8 * 1024 * 1024 * 1024
_FAILS: dict[str, list[float]] = {}


class _TypedStaticFiles(StaticFiles):
    """Set script, style, and font types from the suffix, not the OS map."""

    def file_response(self, full_path, stat_result, scope, status_code=200):  # type: ignore[no-untyped-def]
        response = super().file_response(
            full_path, stat_result, scope, status_code=status_code
        )
        media = media_type_for(str(full_path))
        if media and getattr(response, "status_code", 200) != 304:
            response.headers["content-type"] = media
            if hasattr(response, "media_type"):
                response.media_type = media
        return response


def create_app(
    *,
    data_dir: Path | None = None,
    admin_user: str | None = None,
    admin_password: str | None = None,
    secret: str | None = None,
) -> FastAPI:
    root = paths.data_dir(data_dir)
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
    app.mount("/static", _TypedStaticFiles(directory=str(_ROOT / "static")), name="static")

    @app.middleware("http")
    async def _headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-UA-Compatible"] = "IE=edge"
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
    def latest(request: Request, platform: str = "", current: str = "") -> dict:
        return _serve_latest(store, request, platform, current)

    @app.get("/download/{platform}/{version}")
    def download_version(platform: str, version: str, request: Request) -> FileResponse:
        key = _package_or_404(platform)
        try:
            ver = require_version(version)
        except PackageError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        row = store.get_version(key, ver)
        path = store.blob_path(key, ver)
        if row is None or path is None:
            raise HTTPException(
                status_code=404,
                detail=f"No {package_label(key)} {ver} release is published.",
            )
        _remember_install(
            store,
            request,
            kind="download",
            platform=key,
            published_version=ver,
        )
        return _zip_response(path, row["filename"])

    @app.get("/download/{platform}")
    def download(platform: str, request: Request) -> FileResponse:
        key = _package_or_404(platform)
        row = store.get(key)
        path = store.blob_path(key)
        if row is None or path is None or not row.get("version"):
            raise HTTPException(
                status_code=404,
                detail=f"No {package_label(key)} release is published.",
            )
        _remember_install(
            store,
            request,
            kind="download",
            platform=key,
            published_version=str(row.get("version") or ""),
        )
        return _zip_response(path, row["filename"])

    @app.get("/", response_class=HTMLResponse)
    @app.get("/install", response_class=HTMLResponse)
    def install(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request,
            "install.html",
            _public_context(request, store),
        )

    @app.get("/releases", response_class=HTMLResponse)
    def release_history(request: Request) -> HTMLResponse:
        context = _public_context(request, store)
        context["history"] = store.list_history()
        return _TEMPLATES.TemplateResponse(request, "history.html", context)

    @app.get("/dependencies", response_class=HTMLResponse)
    def dependencies_page(request: Request) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request,
            "tools.html",
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

    @app.get("/admin/analytics", response_class=HTMLResponse)
    def analytics(request: Request, ip: str = "") -> HTMLResponse:
        session = _session_or_redirect(request, app)
        if isinstance(session, RedirectResponse):
            return session
        chosen = _clean_ip(ip)
        return _TEMPLATES.TemplateResponse(
            request,
            "analytics.html",
            {
                "selected_ip": chosen,
                "known": store.list_installations(),
                "detail": _with_live_analytics(store, chosen),
                "csrf": str(session.get("csrf") or ""),
            },
        )

    @app.get("/api/admin/installations")
    def installations_api(request: Request, ip: str = "") -> dict:
        """Install list for the admin page and for one Yaver that has the admin password.

        The public download API does not serve this. A missing or wrong
        password is 403, with no browser login prompt.
        """
        if not _admin_reader(request, app):
            raise HTTPException(status_code=403, detail="Sign in again.")
        chosen = _clean_ip(ip)
        return {
            "installations": store.list_installations(),
            "selected": _with_live_analytics(store, chosen),
        }

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
        kind: str = Form(""),
        csrf: str = Form(""),
        package: UploadFile = File(...),
    ):
        session = _require_admin(request, app, csrf)
        try:
            mode = (kind or "").strip().lower()
            if mode not in ("", "bundle"):
                raise PackageError("Unknown upload.")
            platform_text = (platform or "").strip()
            key = _package_or_404(platform_text) if platform_text else ""
            typed = require_version(version) if (version or "").strip() else ""
            filename = safe_filename(package.filename or "")
            note = _clean_notes(notes)
        except (PackageError, HTTPException) as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            return _admin_again(request, app, session, str(detail))
        blob = root / "incoming.tmp"
        published_as = ""
        try:
            size = 0
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
            use_bundle = mode == "bundle" or (
                key not in DEPENDENCIES and is_executable_bundle(blob)
            )
            if use_bundle:
                if key in DEPENDENCIES:
                    raise PackageError("Upload one dependency zip, not the Yaver bundle.")
                work = Path(tempfile.mkdtemp(prefix="yaver-bundle-", dir=root))
                try:
                    prepared = _prepare_bundle(blob, work, filename, typed, note)
                    store.publish_many(prepared)
                finally:
                    shutil.rmtree(work, ignore_errors=True)
                published_as = "bundle"
            else:
                if not key:
                    raise PackageError("Choose a package.")
                _publish_one(store, blob, key, typed, filename, note)
                published_as = key
        except PackageError as exc:
            return _admin_again(request, app, session, str(exc))
        finally:
            try:
                blob.unlink()
            except OSError:
                pass
        return RedirectResponse(f"/admin?uploaded={published_as}", status_code=303)

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


def _clean_ip(value: str) -> str:
    text = (value or "").strip()
    if not text or len(text) > 64 or any(char in text for char in "\r\n\x00 <>"):
        return ""
    return text


def _clean_client_version(value: str) -> str:
    text = (value or "").strip()
    if not _CLIENT_VERSION.fullmatch(text):
        return ""
    return text


def _with_live_analytics(store: ReleaseStore, ip: str) -> dict | None:
    """One known address, plus a live Analytics read. Unknown addresses are not called."""
    chosen = (ip or "").strip()
    if not chosen:
        return None
    detail = store.installation_detail(chosen)
    if detail is None:
        return None
    out = dict(detail)
    out.pop("usage", None)
    usage, error = fetch_install_analytics(str(out.get("ip") or ""))
    out["usage"] = usage
    out["usage_error"] = error
    return out


def _serve_latest(
    store: ReleaseStore,
    request: Request,
    platform: str,
    current: str,
) -> dict:
    key = _platform_or_404(platform)
    row = store.get(key)
    published = str((row or {}).get("version") or "")
    _remember_install(
        store,
        request,
        kind="latest",
        platform=key,
        client_version=_clean_client_version(current),
        published_version=published,
    )
    if row is None or not published:
        raise HTTPException(
            status_code=404, detail=f"No {PLATFORMS[key]} release is published."
        )
    return row


def _remember_install(
    store: ReleaseStore,
    request: Request,
    *,
    kind: str,
    platform: str,
    client_version: str = "",
    published_version: str = "",
) -> None:
    ip = _clean_ip(request.client.host if request.client else "")
    if not ip:
        return
    try:
        store.record_install_hit(
            ip=ip,
            kind=kind,
            platform=platform,
            client_version=client_version,
            published_version=published_version,
        )
    except Exception as exc:
        _LOG.warning("Could not record install request: %s", exc)


def _basic_admin(request: Request, app: FastAPI) -> bool:
    header = request.headers.get("authorization") or ""
    if not header.lower().startswith("basic "):
        return False
    if not app.state.admin_user or not app.state.admin_password:
        return False
    try:
        decoded = base64.b64decode(header.split(" ", 1)[1].strip(), validate=True)
        text = decoded.decode("utf-8")
    except (ValueError, UnicodeError):
        return False
    username, separator, password = text.partition(":")
    if not separator:
        return False
    return passwords_match(app.state.admin_user, username) and passwords_match(
        app.state.admin_password, password
    )


def _admin_reader(request: Request, app: FastAPI) -> bool:
    """Admin cookie or the same username and password over HTTP Basic."""
    if _session(request, app) is not None:
        return True
    return _basic_admin(request, app)


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


def _sha256_file(path: Path) -> tuple[str, int]:
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


def _prepare_bundle(
    blob: Path,
    work: Path,
    upload_name: str,
    typed: str,
    notes: str,
) -> list[dict]:
    prepared: list[dict] = []
    members, file_note = split_executable_bundle(blob, work, upload_name, typed)
    chosen = file_note or notes
    for platform, version, name, part in members:
        flatten_wrapper(part)
        layout = inspect_zip(part)
        if layout != "frozen":
            raise PackageError(f"{name} is not an executable package.")
        inside = version_from_zip(part)
        if inside and inside != version:
            raise PackageError(f"{name} says {inside} in VERSION.")
        try:
            ensure_updater(part, platform)
        except (OSError, zipfile.BadZipFile) as exc:
            raise PackageError("The update script could not be added to the zip.") from exc
        digest, size = _sha256_file(part)
        prepared.append(
            {
                "platform": platform,
                "version": version,
                "filename": name,
                "sha256": digest,
                "size": size,
                "layout": layout,
                "notes": chosen,
                "blob": part,
            }
        )
    return prepared


def _publish_one(
    store: ReleaseStore,
    blob: Path,
    key: str,
    typed: str,
    filename: str,
    note: str,
) -> None:
    layout = inspect_zip(blob)
    inside = version_from_zip(blob)
    if inside and typed and inside != typed:
        raise PackageError(f"The VERSION file says {inside}.")
    ver = inside or typed
    if not ver:
        raise PackageError("Type a version, or put a VERSION file at the top of the zip.")
    if layout == "frozen":
        try:
            ensure_updater(blob, key)
        except (OSError, zipfile.BadZipFile) as exc:
            raise PackageError("The update script could not be added to the zip.") from exc
    digest, size = _sha256_file(blob)
    store.publish(
        platform=key,
        version=ver,
        filename=filename,
        sha256=digest,
        size=size,
        layout=layout,
        notes=note,
        blob=blob,
    )


def _notice_for(uploaded: str, saved: str) -> str:
    if uploaded == "bundle":
        labels = list(PLATFORMS.values())
        names = ", ".join(labels[:-1]) + ", and " + labels[-1]
        return f"Published the {names} packages."
    if uploaded in PLATFORMS or uploaded in DEPENDENCIES:
        return f"Published the {package_label(uploaded)} package."
    if saved == "text":
        return "Saved the page text."
    if saved == "reset":
        return "Restored the original page text."
    return ""


def _zip_response(path: Path, filename: str) -> FileResponse:
    return FileResponse(
        path,
        media_type="application/zip",
        filename=filename,
        content_disposition_type="attachment",
    )


def _dependency_groups(rows: list[dict]) -> list[dict]:
    by_platform = {str(row["platform"]): row for row in rows}
    specs = (
        ("opencode", "OpenCode", "opencode_windows", "opencode_linux"),
        ("claude", "Claude Code", "claude_windows", "claude_linux"),
        ("codex", "Codex", "codex_windows", "codex_linux"),
    )
    groups: list[dict] = []
    for tool, label, windows_copy, linux_copy in specs:
        sample_name, sample = SAMPLE_CONFIGS[tool]
        windows_config, linux_config = CONFIG_DESTINATIONS[tool]
        groups.append(
            {
                "id": tool,
                "label": label,
                "windows_copy": windows_copy,
                "linux_copy": linux_copy,
                "windows_row": by_platform.get(f"{tool}-windows", {}),
                "linux_row": by_platform.get(f"{tool}-linux", {}),
                "sample_name": sample_name,
                "windows_config": windows_config,
                "linux_config": linux_config,
                "sample": sample,
                "sample_rows": max(sample.count("\n"), 1),
            }
        )
    return groups


def _public_context(request: Request, store: ReleaseStore) -> dict:
    dependency_rows = store.list_dependencies()
    stored = store.copy_map()
    intro = stored["deps_intro"] if "deps_intro" in stored else DEFAULTS["deps_intro"]
    return {
        "releases": store.list_all(),
        "dependency_rows": dependency_rows,
        "dependencies": _dependency_groups(dependency_rows),
        "sections": _public_sections(request, store),
        "cert_url": certificate_url(intro),
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
