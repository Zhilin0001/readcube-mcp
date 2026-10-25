import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from readcube_client.auth import (
    LoginFailure,
    load_cookies,
    password_login,
    private_json_write,
    save_cookies,
    session_status,
    validate_saved_session,
)
from readcube_client.errors import AuthenticationError


def session(path: Path, *, expires=None):
    private_json_write(
        path,
        {
            "cookies": [
                {
                    "name": "session",
                    "value": "existing-fake",
                    "domain": ".readcube.com",
                    "expires": expires,
                }
            ]
        },
    )


def test_expired_local_session_rejected(tmp_path):
    path = tmp_path / "session.json"
    session(path, expires=10)
    with pytest.raises(LoginFailure) as error:
        load_cookies(path, now=11)
    assert error.value.code == "session_expired"


def test_expired_cookie_removed_without_discarding_valid_cookie(tmp_path):
    path = tmp_path / "session.json"
    private_json_write(
        path,
        {
            "cookies": [
                {"name": "old", "value": "expired", "domain": ".readcube.com", "expires": 1},
                {"name": "current", "value": "valid", "domain": ".readcube.com", "expires": 20},
            ]
        },
    )
    assert [cookie.name for cookie in load_cookies(path, now=10).jar] == ["current"]


@pytest.mark.parametrize("expiry", ["tomorrow", True, float("nan"), float("inf")])
def test_invalid_expiry_rejected(tmp_path, expiry):
    path = tmp_path / "session.json"
    session(path, expires=expiry)
    with pytest.raises(AuthenticationError, match="expiry"):
        load_cookies(path)


def test_status_does_not_claim_server_verified(tmp_path):
    path = tmp_path / "session.json"
    session(path)
    status = session_status(path)
    assert status["server_verified"] is False
    assert status["has_session_cookies"] is True
    assert "existing-fake" not in json.dumps(status)


def test_symlink_and_non_regular_session_rejected(tmp_path):
    path = tmp_path / "session.json"
    session(path)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(AuthenticationError, match="symlink"):
        load_cookies(link)
    with pytest.raises(AuthenticationError, match="regular"):
        load_cookies(tmp_path)
    with pytest.raises(AuthenticationError, match="symlink"):
        save_cookies(load_cookies(path), link)


def test_password_login_verifies_and_saves_without_credentials(tmp_path):
    path = tmp_path / "session.json"
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            form = parse_qs(request.content.decode(), keep_blank_values=True)
            assert form["email"] == ["fake@example.org"]
            assert form["password"] == ["not-real-password"]
            assert "cookie" not in request.headers
            return httpx.Response(
                302,
                headers={
                    "set-cookie": "session=new-fake; Domain=.readcube.com; Path=/; Secure",
                    "location": "https://app.readcube.com",
                },
            )
        assert request.url.path == "/collections"
        assert request.headers["cookie"] == "session=new-fake"
        return httpx.Response(200, json={"collections": [{"id": "test-library"}]})

    result = password_login(
        " fake@example.org ", "not-real-password", path, transport=httpx.MockTransport(handler)
    )
    assert result == {
        "authenticated": True,
        "collection_count": 1,
        "flow": "password",
        "saved": True,
    }
    assert len(calls) == 2
    assert path.stat().st_mode & 0o777 == 0o600
    assert [c.value for c in load_cookies(path).jar] == ["new-fake"]
    assert "password" not in path.read_text()
    assert "fake@example.org" not in path.read_text()


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "credentials_rejected"),
        (403, "access_rejected"),
        (429, "rate_limited"),
        (503, "service_unavailable"),
    ],
)
def test_failed_login_does_not_retry_or_overwrite_session(tmp_path, status, code):
    path = tmp_path / "session.json"
    session(path)
    before = path.read_bytes()
    calls = []

    def handler(request):
        calls.append(request)
        assert "cookie" not in request.headers
        return httpx.Response(status, text="secret-response-data")

    with pytest.raises(LoginFailure) as error:
        password_login(
            "fake@example.org", "fake-password", path, transport=httpx.MockTransport(handler)
        )
    assert error.value.code == code
    assert error.value.status == status
    assert "secret-response-data" not in str(error.value)
    assert path.read_bytes() == before
    assert len(calls) == 1


def test_login_cookie_is_not_itself_success(tmp_path):
    path = tmp_path / "session.json"
    session(path)
    before = path.read_bytes()

    def handler(request):
        if request.method == "POST":
            return httpx.Response(
                200, headers={"set-cookie": "tracking=fake; Domain=.readcube.com; Secure"}
            )
        return httpx.Response(401)

    with pytest.raises(LoginFailure):
        password_login(
            "fake@example.org", "fake-password", path, transport=httpx.MockTransport(handler)
        )
    assert path.read_bytes() == before


def test_no_cookies_leaves_interactive_auth_unresolved(tmp_path):
    with pytest.raises(LoginFailure) as error:
        password_login(
            "fake@example.org",
            "fake-password",
            tmp_path / "session",
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"mfa": True})),
        )
    assert error.value.code == "interactive_auth_required"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>login</html>"),
        httpx.Response(200, json={"collections": [], "error": "redacted"}),
        httpx.Response(200, json={"collections": ["wrong-shape"]}),
        httpx.Response(200, json={"collections": [{"name": "missing-id"}]}),
        httpx.Response(302, headers={"location": "https://sso.example.com"}),
    ],
)
def test_session_validation_rejects_login_and_error_envelopes(tmp_path, response):
    path = tmp_path / "session.json"
    session(path)
    before = path.read_bytes()
    with pytest.raises(LoginFailure):
        validate_saved_session(path, transport=httpx.MockTransport(lambda r: response))
    assert path.read_bytes() == before


def test_validate_saves_rotated_cookie_only_after_read_success(tmp_path):
    path = tmp_path / "session.json"
    session(path)
    result = validate_saved_session(
        path,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={"collections": []},
                headers={
                    "set-cookie": "session=rotated-fake; Domain=.readcube.com; Path=/; Secure"
                },
            )
        ),
    )
    assert result["cookies_changed"] is True
    assert [cookie.value for cookie in load_cookies(path).jar] == ["rotated-fake"]


def test_validate_can_avoid_saving_rotated_cookies(tmp_path):
    path = tmp_path / "session.json"
    session(path)
    before = path.read_bytes()
    result = validate_saved_session(
        path,
        persist_cookies=False,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={"collections": []},
                headers={
                    "set-cookie": "session=rotated-fake; Domain=.readcube.com; Path=/; Secure"
                },
            )
        ),
    )
    assert result["cookies_changed"] is True
    assert result["saved"] is False
    assert path.read_bytes() == before


def test_transport_failure_redacts_exception_and_does_not_retry(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("secret from network exception", request=request)

    with pytest.raises(LoginFailure) as error:
        password_login(
            "fake@example.org",
            "fake-password",
            tmp_path / "session",
            transport=httpx.MockTransport(handler),
        )
    assert error.value.code == "network_error"
    assert "secret" not in str(error.value)
    assert len(calls) == 1
