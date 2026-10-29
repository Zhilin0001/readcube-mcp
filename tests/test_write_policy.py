import asyncio
import json

import httpx
import pytest

from readcube_client import WriteAuthorization
from readcube_client.errors import AuthorizationError, ProtocolError
from readcube_client.write_policy import set_library_access, write_allowed
from readcube_mcp.server import create_server


def handler(request):
    if request.url.path == "/collections":
        return httpx.Response(
            200,
            json={
                "collections": [
                    {"id": "lib1", "name": "Research"},
                    {"id": "lib2", "name": "Other"},
                ]
            },
        )
    return httpx.Response(200, json={"item": {"id": "paper"}})


def test_default_all_permits_authorized_writes_and_denied_library_stops_them(make_client):
    client = make_client(handler, verified=["list_collections", "update_notes"], write_policy="all")
    auth = WriteAuthorization(collection_id="lib1", authorized=True)
    assert write_allowed(client, "lib1") and write_allowed(client, "lib2")
    with pytest.raises(AuthorizationError):
        client.update_notes("lib1", "paper", "text", dry_run=False)
    preview = set_library_access(client, "Research", False)
    assert preview["write_allowed_before"] and not preview["write_allowed_after"]
    assert write_allowed(client, "lib1")
    with pytest.raises(AuthorizationError):
        set_library_access(client, "Research", False, dry_run=False)
    saved = set_library_access(client, "Research", False, dry_run=False, authorized=True)
    assert saved["saved"] and not write_allowed(client, "lib1")
    assert write_allowed(client, "lib2")
    with pytest.raises(AuthorizationError, match="disabled"):
        client.update_notes("lib1", "paper", "text", authorization=auth, dry_run=False)
    assert client.update_notes("lib1", "paper", "text", dry_run=True).operation == "update_notes"
    set_library_access(client, "lib1", True, authorized=True, dry_run=False)
    assert write_allowed(client, "lib1")


def test_policy_survives_new_clients_sessions_and_allowlist_is_opt_in(make_client):
    first = make_client(handler, verified=["list_collections"], write_policy="all")
    set_library_access(first, "lib1", False, authorized=True, dry_run=False)
    second = make_client(handler, verified=["list_collections"], write_policy="all")
    second.session = "a-new-login"
    assert not write_allowed(second, "lib1") and write_allowed(second, "lib2")
    second.settings.write_policy = "allowlist"
    second.settings.write_collections = ["lib1"]
    result = set_library_access(second, "lib2", True, authorized=True, dry_run=False)
    assert not result["write_allowed_after"] and not write_allowed(second, "lib2")


def test_policy_refuses_ambiguous_names_and_corrupt_policy(make_client, monkeypatch):
    client = make_client(handler, verified=["list_collections"], write_policy="all")
    monkeypatch.setattr(
        client,
        "list_collections",
        lambda: [{"id": "one", "name": "same"}, {"id": "two", "name": "same"}],
    )
    with pytest.raises(ValueError, match="exactly one"):
        set_library_access(client, "same", False, authorized=True, dry_run=False)
    path = client.settings.state_dir / "write-policy.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"blocked": "not a list"}))
    with pytest.raises(ProtocolError, match="blocked"):
        write_allowed(client, "one")


def test_queued_write_rechecks_policy_before_sending(make_client, monkeypatch):
    methods = []

    def tracked(request):
        methods.append(request.method)
        return handler(request)

    client = make_client(tracked, verified=["list_collections", "update_notes"], write_policy="all")
    original = client._check_authorization
    checks = 0

    def check(*args, **kwargs):
        nonlocal checks
        original(*args, **kwargs)
        checks += 1
        if checks == 1:
            set_library_access(client, "lib1", False, authorized=True, dry_run=False)

    monkeypatch.setattr(client, "_check_authorization", check)
    with pytest.raises(AuthorizationError, match="disabled"):
        client.update_notes(
            "lib1",
            "paper",
            "text",
            authorization=WriteAuthorization(collection_id="lib1", authorized=True),
            dry_run=False,
        )
    assert "POST" not in methods


def test_mcp_can_preview_then_change_one_policy(make_client):
    client = make_client(handler, verified=["list_collections"], write_policy="all")
    client.close = lambda: None
    server = create_server(lambda: client)

    async def check():
        result = await server.call_tool(
            "readcube_set_library_write_access", {"collection": "Other", "allow": False}
        )
        assert result.structured_content["dry_run"] and write_allowed(client, "lib2")
        result = await server.call_tool(
            "readcube_set_library_write_access",
            {"collection": "Other", "allow": False, "authorized": True, "dry_run": False},
        )
        assert result.structured_content["saved"] and not write_allowed(client, "lib2")

    asyncio.run(check())
