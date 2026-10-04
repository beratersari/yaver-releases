"""Admin session cookie. The download API stays open on the LAN."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

COOKIE = "yaver_release_session"
_MAX_AGE = 12 * 60 * 60


def load_secret(data_dir: Path, explicit: str | None) -> str:
    text = (explicit or "").strip()
    if text:
        return text
    path = data_dir / "secret.key"
    if path.is_file():
        saved = path.read_text(encoding="utf-8").strip()
        if saved:
            return saved
    path.parent.mkdir(parents=True, exist_ok=True)
    generated = secrets.token_urlsafe(32)
    path.write_text(generated + "\n", encoding="utf-8")
    return generated


def new_csrf() -> str:
    return secrets.token_urlsafe(24)


def sign_session(secret: str, *, user: str, csrf: str) -> str:
    return _sign_kind(secret, kind="admin", user=user, csrf=csrf)


def sign_csrf(secret: str, *, csrf: str) -> str:
    return _sign_kind(secret, kind="csrf", user="", csrf=csrf)


def read_session(secret: str, token: str) -> dict | None:
    data = _read_kind(secret, token, kind="admin")
    if data is None:
        return None
    if not str(data.get("user") or "").strip():
        return None
    return data


def read_csrf(secret: str, token: str) -> dict | None:
    return _read_kind(secret, token, kind="csrf")


def _sign_kind(secret: str, *, kind: str, user: str, csrf: str) -> str:
    payload = {
        "kind": kind,
        "user": user,
        "csrf": csrf,
        "exp": int(time.time()) + _MAX_AGE,
    }
    return _sign(secret, payload)


def _read_kind(secret: str, token: str, *, kind: str) -> dict | None:
    data = _unsign(secret, token)
    if not data or data.get("kind") != kind:
        return None
    if not str(data.get("csrf") or "").strip():
        return None
    return data


def passwords_match(stored: str, given: str) -> bool:
    left = hashlib.sha256(stored.encode("utf-8")).digest()
    right = hashlib.sha256(given.encode("utf-8")).digest()
    return hmac.compare_digest(left, right)


def csrf_ok(expected: str, given: str) -> bool:
    if not expected or not given:
        return False
    return hmac.compare_digest(expected, given)


def _sign(secret: str, payload: dict) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    raw = base64.urlsafe_b64encode(body).decode("ascii").rstrip("=")
    return f"{raw}.{mac}"


def _unsign(secret: str, token: str) -> dict | None:
    if not token or "." not in token:
        return None
    raw, mac = token.rsplit(".", 1)
    try:
        body = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        expect = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expect, mac):
            return None
        data = json.loads(body.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        exp = int(data.get("exp") or 0)
    except (TypeError, ValueError):
        return None
    if exp < int(time.time()):
        return None
    return data
