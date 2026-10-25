import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest

from readcube_client import Settings
from readcube_client.auth import load_cookies, private_json_write
from readcube_client.errors import AuthenticationError
from readcube_mcp.runtime import ReadCubeClientPool


@pytest.fixture
def pool_setup(tmp_path):
    settings = Settings(
        _env_file=None,
        session_file=tmp_path / "session.json",
        verification_file=tmp_path / "verified.json",
        state_dir=tmp_path / "state",
        write_collections=["allowed"],
    )
    created = []

    def factory(current):
        client = SimpleNamespace(
            settings=current,
            http=httpx.Client(
                transport=httpx.MockTransport(lambda request: pytest.fail("No real request")),
                cookies=load_cookies(current.session_file)
                if current.session_file.exists()
                else httpx.Cookies(),
            ),
            audit=[],
            _recent_identifiers={},
            _recent_pdf_imports={},
        )
        client.close = client.http.close
        created.append(client)
        return client

    pool = ReadCubeClientPool(
        settings_factory=lambda: settings.model_copy(deep=True),
        client_factory=factory,
        max_clients=2,
    )
    yield pool, settings, created
    pool.close()


def save_session(path, value="test-only", expires=None):
    private_json_write(
        path,
        {
            "cookies": [
                {"name": "session", "value": value, "domain": "readcube.com", "expires": expires}
            ]
        },
    )


def test_connection_reused_audit_bounded_and_shutdown_closed(pool_setup):
    pool, _, created = pool_setup
    with pool() as first:
        first.audit.extend([{}] * 200)
        first._recent_identifiers.update({str(i): str(i) for i in range(300)})
    assert len(first.audit) == 100
    assert len(first._recent_identifiers) == 256
    with pool() as second:
        assert second is first
        assert second.audit == []
        assert not second.http.is_closed
    assert len(created) == 1
    pool.close()
    assert first.http.is_closed
    with pytest.raises(RuntimeError, match="closed"), pool():
        pass


@pytest.mark.parametrize("change", ["settings", "session", "ledger"])
def test_settings_session_and_ledger_changes_retire_connections(pool_setup, change):
    pool, settings, created = pool_setup
    save_session(settings.session_file)
    with pool() as first:
        pass
    if change == "settings":
        settings.write_collections = []
    elif change == "session":
        save_session(settings.session_file, "new-test-only")
    else:
        private_json_write(settings.verification_file, {"operations": {"new": {}}})
    with pool() as second:
        assert second is not first
        assert second.settings.write_collections == settings.write_collections
    assert first.http.is_closed
    assert len(created) == 2


def test_cookie_expiry_and_permissions_checked_on_every_checkout(pool_setup, monkeypatch):
    pool, settings, _ = pool_setup
    save_session(settings.session_file, expires=200)
    monkeypatch.setattr("readcube_client.auth.time.time", lambda: 100)
    with pool() as first:
        pass
    monkeypatch.setattr("readcube_client.auth.time.time", lambda: 201)
    with pytest.raises(AuthenticationError, match="expired"), pool():
        pass
    assert first.http.is_closed
    save_session(settings.session_file)
    with pool() as second:
        pass
    settings.session_file.chmod(0o644)
    with pytest.raises(AuthenticationError, match="0600"), pool():
        pass
    assert second.http.is_closed


def test_lease_is_exclusive_and_slow_tool_does_not_block_another(pool_setup):
    pool, _, created = pool_setup
    entered, release = threading.Event(), threading.Event()

    def slow():
        with pool() as client:
            entered.set()
            assert release.wait(5)
            return client

    with ThreadPoolExecutor(max_workers=2) as executor:
        slow_future = executor.submit(slow)
        assert entered.wait(5)
        try:
            with pool() as fast_client:
                assert fast_client is not created[0]
                assert len(created) == 2
        finally:
            release.set()
        assert slow_future.result(timeout=5) is created[0]


def test_active_lease_not_reused_after_config_change_or_close(pool_setup):
    pool, settings, _ = pool_setup
    with pool() as old:
        settings.write_collections = []
        with pool() as new:
            assert new is not old
            assert not new.settings.write_collections
        assert not old.http.is_closed
    assert old.http.is_closed
    with pool() as current:
        pool.close()
        assert not current.http.is_closed
    assert current.http.is_closed


def test_auth_failure_and_externally_closed_client_are_not_reused(pool_setup):
    pool, _, created = pool_setup
    with pytest.raises(AuthenticationError), pool() as bad:
        raise AuthenticationError("Expired remotely")
    assert bad.http.is_closed
    with pool() as closed:
        closed.http.close()
    with pool() as healthy:
        assert not healthy.http.is_closed
        assert healthy not in (bad, closed)
    assert len(created) == 3


def test_response_cookie_rotation_resets_to_verified_session_but_keeps_connection(pool_setup):
    pool, settings, _ = pool_setup
    save_session(settings.session_file)
    with pool() as old:
        old.http.cookies.set("session", "rotated-test-cookie", domain="readcube.com")
        old.http.cookies.set("other", "new-cookie", domain="readcube.com")
    with pool() as new:
        assert new is old
        assert new.http.cookies.get("session") == "test-only"
        assert new.http.cookies.get("other") is None
    assert not old.http.is_closed


def test_waiting_lease_rechecks_new_configuration(pool_setup):
    pool, settings, _ = pool_setup
    pool._max_clients = 1
    waiting = threading.Event()

    def next_call():
        waiting.set()
        with pool() as client:
            return client.settings.write_collections

    with ThreadPoolExecutor(max_workers=1) as executor:
        with pool():
            result = executor.submit(next_call)
            assert waiting.wait(5)
            settings.write_collections = []
        assert result.result(timeout=5) == []


def test_factory_failure_releases_reserved_slot(tmp_path):
    settings = Settings(
        _env_file=None, session_file=tmp_path / "none", verification_file=tmp_path / "none"
    )
    calls = []

    def failed(current):
        calls.append(True)
        raise ValueError("Construction failed")

    pool = ReadCubeClientPool(
        settings_factory=lambda: settings, client_factory=failed, max_clients=1
    )
    for _ in range(2):
        with pytest.raises(ValueError), pool():
            pass
    assert len(calls) == 2
    pool.close()
