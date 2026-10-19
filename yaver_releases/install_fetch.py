"""Load one install's Analytics when a release admin selects its address.

The version check does not carry these counts. This module GETs
``http://{ip}:{port}/api/analytics/install`` with the same built-in bearer
Yaver checks. ``port`` is that install's dashboard port and defaults to
8080. The token is not an operator setting. Do not log it, and do not put
it on a query string.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re

import httpx

# Same value as src/dashboard/install_analytics.py in the Yaver repo.
INSTALL_ANALYTICS_TOKEN = "c4e8a1b7d2f6093c5e8a4b1d7f0c6e9a2b5d8f1c4e7a0b3d6f9c2e5a8b1d4f70"
INSTALL_ANALYTICS_PORT = 8080
# Forty error jobs, each with a 2000-character message, plus the count report.
_MAX_BODY = 512 * 1024
_ERROR_ROW_LIMIT = 40
_MESSAGE_LIMIT = 2000
_URL_USERINFO = re.compile(r"(?i)(https?://)[^/\s@]+(?::[^/\s@]*)?@")
_LOG = logging.getLogger("yaver_releases")


def _usage_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return 0
    try:
        number = int(value)
    except ValueError:
        return 0
    if number < 0:
        return 0
    if number > 1_000_000:
        return 1_000_000
    return number


def _usage_label(value: object, *, limit: int = 160) -> str:
    text = str(value or "").replace("\x00", " ").replace("\r", " ").replace("\n", " ")
    text = text.replace("<", "").replace(">", "").strip()
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:limit].rstrip()
    return text


def _usage_message(value: object) -> str:
    """Keep line breaks. Drop a value that is not text."""
    if value is None or isinstance(value, (dict, list, bool)):
        return ""
    text = str(value).replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = _URL_USERINFO.sub(r"\1", text).strip()
    if len(text) > _MESSAGE_LIMIT:
        text = text[:_MESSAGE_LIMIT].rstrip()
    return text


def _usage_errors(value: object) -> tuple[list[dict], int]:
    if not isinstance(value, list):
        return [], 0
    rows: list[dict] = []
    dropped = 0
    for item in value:
        if not isinstance(item, dict):
            dropped += 1
            continue
        if len(rows) >= _ERROR_ROW_LIMIT:
            dropped += 1
            continue
        rows.append(
            {
                "job_id": _usage_label(item.get("job_id"), limit=80),
                "issue_key": _usage_label(item.get("issue_key"), limit=40),
                "summary": _usage_label(item.get("summary")),
                "status": _usage_label(item.get("status"), limit=40),
                "category": _usage_label(item.get("category"), limit=40),
                "source": _usage_label(item.get("source"), limit=40),
                "backend": _usage_label(item.get("backend"), limit=40),
                "agent": _usage_label(item.get("agent"), limit=80),
                "model": _usage_label(item.get("model")),
                "repository": _usage_label(item.get("repository")),
                "started_at": _usage_label(item.get("started_at"), limit=40),
                "completed_at": _usage_label(item.get("completed_at"), limit=40),
                "error_message": _usage_message(item.get("error_message")),
            }
        )
    return rows, dropped


def _usage_group(value: object) -> dict[str, int]:
    raw = value if isinstance(value, dict) else {}
    return {
        "opened": _usage_int(raw.get("opened")),
        "merged": _usage_int(raw.get("merged")),
        "closed": _usage_int(raw.get("closed")),
        "total": _usage_int(raw.get("total")),
    }


def _usage_rows(value: object, *, outcomes: bool) -> list[dict]:
    if not isinstance(value, list):
        return []
    rows: list[dict] = []
    for item in value[:12]:
        if not isinstance(item, dict):
            continue
        label = _usage_label(item.get("label"))
        if not label:
            continue
        row: dict = {"label": label, "jobs": _usage_int(item.get("jobs"))}
        if outcomes:
            row.update(
                {
                    "completed": _usage_int(item.get("completed")),
                    "error": _usage_int(item.get("error")),
                    "cancelled": _usage_int(item.get("cancelled")),
                    "plan_ready": _usage_int(item.get("plan_ready")),
                    "in_flight": _usage_int(item.get("in_flight")),
                }
            )
        rows.append(row)
    return rows


def clean_usage(value: object) -> dict | None:
    """Keep counts, short labels, and the error-job list. Drop anything else."""
    if not isinstance(value, dict):
        return None
    errors, extra_omitted = _usage_errors(value.get("errors"))
    return {
        "period": "all",
        "jobs": _usage_int(value.get("jobs")),
        "completed": _usage_int(value.get("completed")),
        "error": _usage_int(value.get("error")),
        "cancelled": _usage_int(value.get("cancelled")),
        "plan_ready": _usage_int(value.get("plan_ready")),
        "in_flight": _usage_int(value.get("in_flight")),
        "merge_requests": _usage_int(value.get("merge_requests")),
        "opened": _usage_int(value.get("opened")),
        "merged": _usage_int(value.get("merged")),
        "closed": _usage_int(value.get("closed")),
        "ours": _usage_group(value.get("ours")),
        "contributed": _usage_group(value.get("contributed")),
        "categories": _usage_rows(value.get("categories"), outcomes=True),
        "sources": _usage_rows(value.get("sources"), outcomes=True),
        "models": _usage_rows(value.get("models"), outcomes=True),
        "backends": _usage_rows(value.get("backends"), outcomes=True),
        "agents": _usage_rows(value.get("agents"), outcomes=True),
        "repositories": _usage_rows(value.get("repositories"), outcomes=False),
        "statuses": _usage_rows(value.get("statuses"), outcomes=False),
        "errors": errors,
        "errors_omitted": _usage_int(value.get("errors_omitted")) + extra_omitted,
        "errors_available": isinstance(value.get("errors"), list),
    }


def _callable_host(ip: str) -> tuple[str, str]:
    """Return ``(host, "")`` or ``("", error)``. Host is safe to put in a URL."""
    try:
        address = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return "", "This address is not an IP address."
    # Loopback is also marked reserved. It is still this machine's own install.
    if not address.is_loopback and (
        address.is_unspecified
        or address.is_multicast
        or address.is_link_local
        or address.is_reserved
    ):
        return "", "This address is not requested."
    host = address.compressed
    if address.version == 6:
        host = f"[{host}]"
    return host, ""


def effective_listen_port(port: int | None = None) -> int:
    """Dashboard port to call. ``None`` uses the default, which tests may replace."""
    chosen = INSTALL_ANALYTICS_PORT if port is None else port
    if isinstance(chosen, bool) or not isinstance(chosen, int):
        return 0
    if chosen < 1 or chosen > 65535:
        return 0
    return chosen


def format_install_address(ip: str, port: int) -> str:
    """``ip:port`` for the admin list. IPv6 is shown in brackets."""
    text = (ip or "").strip()
    try:
        parsed = ipaddress.ip_address(text)
    except ValueError:
        host = text
    else:
        host = parsed.compressed
        if parsed.version == 6:
            host = f"[{host}]"
    return f"{host}:{port}"


def analytics_url(ip: str, port: int | None = None) -> str:
    """Absolute URL for one install, or ``""`` when that address is not called."""
    host, error = _callable_host(ip)
    if error or not host:
        return ""
    listen = effective_listen_port(port)
    if not listen:
        return ""
    return f"http://{host}:{listen}/api/analytics/install"


def _read_capped(response: httpx.Response) -> bytes | None:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > _MAX_BODY:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_install_analytics(ip: str, port: int | None = None) -> tuple[dict | None, str]:
    """GET one install. ``error`` is empty when ``usage`` is present.

    Call this only for an address already stored from a version check.
    ``port`` is that install's dashboard port. A hostname, a link-local
    address, or any other non-callable IP is refused here as well, before
    a socket opens.
    """
    host, error = _callable_host(ip)
    if error:
        return None, error
    listen = effective_listen_port(port)
    if not listen:
        return None, "Could not reach this install."
    url = f"http://{host}:{listen}/api/analytics/install"
    # INTENTIONAL: verify=False. http only, redirects are not followed,
    # and trust_env keeps the bearer off a corporate proxy.
    timeout = httpx.Timeout(5.0, connect=3.0)
    headers = {
        "Authorization": f"Bearer {INSTALL_ANALYTICS_TOKEN}",
        "Accept": "application/json",
        "Accept-Encoding": "identity",
    }
    try:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
    try:
        with httpx.Client(
            timeout=timeout,
            verify=False,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            with client.stream("GET", url, headers=headers) as response:
                status = response.status_code
                if 300 <= status < 400:
                    return None, "This install redirected the analytics request."
                if status == 403:
                    return None, "This install refused the analytics request."
                if status == 404:
                    return None, "This install does not serve analytics on this path yet."
                if status != 200:
                    return None, f"This install returned HTTP {status}."
                raw = _read_capped(response)
    except Exception as exc:
        _LOG.info("Install analytics request failed: %s", type(exc).__name__)
        return None, f"Could not reach this install on port {listen}."
    if raw is None:
        return None, "This install returned analytics that were too large."
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return None, "This install returned analytics that could not be read."
    cleaned = clean_usage(payload)
    if cleaned is None:
        return None, "This install returned analytics that could not be read."
    return cleaned, ""
