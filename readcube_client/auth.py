"""Local session storage and explicit, non-interactive password authentication.

The password endpoint is a researched flow, not a general SSO/MFA client.  A
successful HTTP response is insufficient: cookies are saved only after the
current collections endpoint independently accepts the new session.
"""

import hashlib
import json
import logging
import math
import os
import stat
import tempfile
import time
from datetime import UTC, datetime
from http.cookiejar import Cookie
from pathlib import Path

import httpx

from .errors import AuthenticationError

COOKIE_DOMAINS = {"readcube.com", "sync.readcube.com", "services.readcube.com", "app.readcube.com"}
LOGIN_URL = "https://services.readcube.com/authentication/login"
COLLECTIONS_URL = "https://services.readcube.com/collections"


class LoginFailure(AuthenticationError):
    """Stable, sanitized failure reason; never includes response bodies or URLs."""

    def __init__(self, code: str, message: str, *, status: int | None = None):
        self.code = code
        self.status = status
        super().__init__(message)


def private_json_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".readcube-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _cookie_records(cookies: httpx.Cookies) -> list[dict]:
    return [
        {
            "name": c.name,
            "value": c.value,
            "domain": c.domain,
            "domain_specified": c.domain_specified,
            "path": c.path,
            "secure": c.secure,
            "expires": c.expires,
            "discard": c.discard,
        }
        for c in cookies.jar
    ]


def _cookies_from_records(records: object, *, now: float | None = None) -> httpx.Cookies:
    now = time.time() if now is None else now
    if not isinstance(records, list):
        raise AuthenticationError("Invalid session cookie records")
    cookies = httpx.Cookies()
    expired = 0
    for row in records:
        if not isinstance(row, dict):
            raise AuthenticationError("Invalid session cookie record")
        domain = row.get("domain")
        if not isinstance(domain, str) or domain.lstrip(".") not in COOKIE_DOMAINS:
            raise AuthenticationError("Session contains an unexpected cookie domain")
        name, value, path = row.get("name"), row.get("value"), row.get("path", "/")
        if (
            not isinstance(name, str)
            or not name
            or any(c in name for c in "\r\n;= \t")
            or not isinstance(value, str)
            or any(c in value for c in "\r\n")
            or not isinstance(path, str)
            or not path.startswith("/")
            or any(c in path for c in "\r\n")
        ):
            raise AuthenticationError("Invalid session cookie fields")
        expires = row.get("expires")
        if expires is not None and (
            isinstance(expires, bool)
            or not isinstance(expires, (int, float))
            or not math.isfinite(expires)
        ):
            raise AuthenticationError("Invalid session cookie expiry")
        if expires is not None and expires <= now:
            expired += 1
            continue
        secure = row.get("secure", True)
        domain_specified = row.get("domain_specified", True)
        discard = row.get("discard", expires is None)
        if not all(isinstance(flag, bool) for flag in (secure, domain_specified, discard)):
            raise AuthenticationError("Invalid session cookie flags")
        cookies.jar.set_cookie(
            Cookie(
                version=0,
                name=name,
                value=value,
                port=None,
                port_specified=False,
                domain=domain,
                domain_specified=domain_specified,
                domain_initial_dot=domain.startswith("."),
                path=path,
                path_specified=True,
                secure=secure,
                expires=expires,
                discard=discard,
                comment=None,
                comment_url=None,
                rest={},
                rfc2109=False,
            )
        )
    if not list(cookies.jar):
        if expired:
            raise LoginFailure("session_expired", "Local session cookies expired; log in again")
        raise LoginFailure("no_session", "No session cookies; run scripts/login_local.py")
    return cookies


def load_cookies(path: Path, *, now: float | None = None) -> httpx.Cookies:
    if path.is_symlink():
        raise AuthenticationError("Session file must not be a symlink")
    try:
        mode = path.stat().st_mode
        if not stat.S_ISREG(mode):
            raise AuthenticationError("Session path must be a regular file")
        if os.name == "posix" and stat.S_IMODE(mode) & 0o077:
            raise AuthenticationError("Session file must have permissions 0600")
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise AuthenticationError("Invalid local session")
        return _cookies_from_records(data["cookies"], now=now)
    except (OSError, ValueError, KeyError, TypeError):
        raise AuthenticationError(
            "Missing or invalid local session; run scripts/login_local.py"
        ) from None


def save_cookies(cookies: httpx.Cookies, path: Path) -> None:
    """Persist allowed, unexpired cookies atomically without email or password."""
    if path.is_symlink():
        raise AuthenticationError("Session file must not be a symlink")
    valid = _cookies_from_records(_cookie_records(cookies))
    try:
        private_json_write(
            path,
            {
                "schema_version": 1,
                "saved_at": datetime.now(UTC).isoformat(),
                "cookies": _cookie_records(valid),
            },
        )
    except OSError:
        raise LoginFailure("storage_error", "Unable to save private session file") from None


def session_fingerprint(cookies: httpx.Cookies) -> str:
    values = sorted((c.domain, c.path, c.name, c.value) for c in cookies.jar)
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def session_status(path: Path) -> dict:
    """Inspect local expiry only; this does not claim server authentication."""
    cookies = load_cookies(path)
    expiries = [cookie.expires for cookie in cookies.jar if cookie.expires is not None]
    return {
        "local_state": "available",
        "server_verified": False,
        "cookie_count": len(list(cookies.jar)),
        "earliest_expiry": min(expiries) if expiries else None,
        "has_session_cookies": any(cookie.expires is None for cookie in cookies.jar),
    }


def _quiet_http_logging() -> None:
    for name in ("httpx", "httpcore", "httpx2", "httpcore2"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _check_http_status(response: httpx.Response, *, stage: str) -> None:
    status = response.status_code
    if status == 429:
        raise LoginFailure(
            "rate_limited", "Authentication rate limited; no retry sent", status=status
        )
    if status >= 500:
        raise LoginFailure(
            "service_unavailable", "Authentication service unavailable", status=status
        )
    if status in (401, 403):
        # A 403 is not reliable evidence that the password was wrong.
        code = "credentials_rejected" if stage == "login" and status == 401 else "access_rejected"
        raise LoginFailure(code, f"Authentication rejected (HTTP {status})", status=status)
    allowed = (200, 201, 204, 302) if stage == "login" else (200,)
    if status not in allowed:
        code = "interactive_auth_required" if 300 <= status < 400 else "unexpected_response"
        raise LoginFailure(code, f"Authentication incomplete (HTTP {status})", status=status)


def _verify_session(client: httpx.Client, *, client_version: str) -> dict:
    response = client.get(
        COLLECTIONS_URL,
        params={"client": "webapp", "client_id": "", "client_version": client_version},
    )
    _check_http_status(response, stage="verify")
    try:
        data = response.json()
    except ValueError:
        raise LoginFailure(
            "unexpected_response", "Session verification did not return API JSON"
        ) from None
    if (
        not isinstance(data, dict)
        or data.get("status") not in (None, "ok", "success")
        or data.get("error")
        or not isinstance(data.get("collections"), list)
        or not all(
            isinstance(row, dict) and isinstance(row.get("id"), str) for row in data["collections"]
        )
    ):
        raise LoginFailure(
            "unexpected_response", "Session verification returned an invalid envelope"
        )
    return {"authenticated": True, "collection_count": len(data["collections"])}


def validate_saved_session(
    path: Path,
    *,
    client_version: str = "5.4.24",
    timeout: float = 30,
    persist_cookies: bool = True,
    transport: httpx.BaseTransport | None = None,
) -> dict:
    """Validate with a read-only API call, optionally saving server cookie rotation.

    This does not invent a refresh-token endpoint.  An expired/revoked session
    requires a new normal login.  Cookie changes invalidate session-bound SDK
    verification evidence, as intended.
    """
    _quiet_http_logging()
    cookies = load_cookies(path)
    try:
        with httpx.Client(
            cookies=cookies,
            timeout=timeout,
            follow_redirects=False,
            transport=transport,
            headers={"Accept": "application/json"},
        ) as client:
            result = _verify_session(client, client_version=client_version)
            changed = _cookie_records(cookies) != _cookie_records(client.cookies)
            session_changed = session_fingerprint(cookies) != session_fingerprint(client.cookies)
            if persist_cookies:
                save_cookies(client.cookies, path)
            return {
                **result,
                "cookies_changed": changed,
                "session_changed": session_changed,
                "saved": persist_cookies,
            }
    except httpx.HTTPError:
        raise LoginFailure(
            "network_error", "Authentication network failure; no retry sent"
        ) from None


def password_login(
    email: str,
    password: str,
    session_file: Path,
    *,
    client_version: str = "5.4.24",
    timeout: float = 30,
    transport: httpx.BaseTransport | None = None,
) -> dict:
    """Explicit password-flow helper; no SSO/MFA or automatic credential retry.

    Uses a fresh cookie jar so a previous session cannot make a failed login
    appear successful.  Existing local credentials survive every failed attempt.
    Raw HTTP responses and secrets are never returned.
    """
    if (
        not isinstance(email, str)
        or not email.strip()
        or not isinstance(password, str)
        or not password
    ):
        raise ValueError("Email and password are required")
    _quiet_http_logging()
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            transport=transport,
            headers={"Accept": "application/json"},
        ) as client:
            response = client.post(
                LOGIN_URL,
                data={
                    "client": "webapp",
                    "api": "",
                    "client_version": client_version,
                    "email": email.strip(),
                    "password": password,
                },
            )
            _check_http_status(response, stage="login")
            try:
                _cookies_from_records(_cookie_records(client.cookies))
            except AuthenticationError:
                raise LoginFailure(
                    "interactive_auth_required",
                    "Login did not produce a usable session; complete normal browser authentication",
                ) from None
            result = _verify_session(client, client_version=client_version)
            save_cookies(client.cookies, session_file)
            return {**result, "flow": "password", "saved": True}
    except httpx.HTTPError:
        raise LoginFailure(
            "network_error", "Authentication network failure; no retry sent"
        ) from None
