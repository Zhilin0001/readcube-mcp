import json

import httpx
import pytest

from readcube_client.batch_import import batch_import_dois
from readcube_client.errors import AuthorizationError, ProtocolError, UnverifiedEndpointError

VERIFIED = [
    "list_items",
    "list_lists",
    "list_list_items",
    "get_item",
    "import_identifier",
    "add_to_list",
]


def client_setup(make_client, *, fail_post=False, delay_list=False):
    rows = {"old": {"id": "old", "ext_ids": {"doi": "10.1234/old"}}}
    memberships = set()
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        path = request.url.path
        if path.endswith("/lists"):
            return httpx.Response(200, json={"lists": [{"id": "list1"}]})
        if path.endswith("/lists/list1/items"):
            members = [] if delay_list else [rows[i] for i in memberships]
            return httpx.Response(200, json={"items": members, "total": len(members)})
        if path.endswith("/lists/list1/add_items"):
            memberships.update(json.loads(request.content)["item_ids"])
            return httpx.Response(200, json={"list": {"id": "list1"}})
        if path.endswith("/items") and request.method == "POST":
            if fail_post:
                raise httpx.ReadTimeout("simulated uncertain write")
            doi = json.loads(request.content)["ext_ids"]["doi"]
            item_id = "item" + str(len(rows))
            rows[item_id] = {"id": item_id, "ext_ids": {"doi": doi}}
            return httpx.Response(200, json={"item": rows[item_id]})
        if path.endswith("/items"):
            return httpx.Response(200, json={"items": list(rows.values()), "total": len(rows)})
        item_id = path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={"item": rows[item_id]})

    client = make_client(handler, verified=VERIFIED, write_collections=["lib"])
    return client, rows, calls


def test_batch_one_scan_readback_and_list_membership(make_client):
    client, rows, calls = client_setup(make_client)
    dois = ["10.1234/old", "https://doi.org/10.1234/new", "10.1234/NEW", "10.1234/another"]
    preview = batch_import_dois(client, "lib", dois, list_id="list1")
    assert preview["unique_count"] == 3 and all(method == "GET" for method, _ in calls)
    calls.clear()
    result = batch_import_dois(client, "lib", dois, list_id="list1", authorized=True, dry_run=False)
    assert not result["stopped"] and len(rows) == 3
    assert [x["status"] for x in result["results"]] == ["existing", "imported", "imported"]
    assert all(x["verified"] and x["list_verified"] for x in result["results"])
    assert calls.count(("GET", "/collections/lib/items")) == 1
    assert calls.count(("POST", "/collections/lib/items")) == 2
    assert calls.count(("POST", "/collections/lib/lists/list1/add_items")) == 3
    assert calls.count(("GET", "/collections/lib/lists/list1/items")) == 2
    assert (client.settings.state_dir / "batch-imports/lib.json").stat().st_mode & 0o777 == 0o600


def test_uncertain_import_never_automatically_reposts(make_client):
    client, _, calls = client_setup(make_client, fail_post=True)
    first = batch_import_dois(
        client, "lib", ["10.1234/new", "10.1234/later"], authorized=True, dry_run=False
    )
    assert [x["status"] for x in first["results"]] == ["needs_reconciliation", "not_attempted"]
    second = batch_import_dois(client, "lib", ["10.1234/new"], authorized=True, dry_run=False)
    assert second["results"][0]["status"] == "needs_reconciliation"
    assert calls.count(("POST", "/collections/lib/items")) == 1


def test_unknown_post_result_is_not_claimed_even_if_same_doi_appears(make_client):
    client, rows, calls = client_setup(make_client, fail_post=True)
    first = batch_import_dois(client, "lib", ["10.1234/new"], authorized=True, dry_run=False)
    assert first["results"][0]["status"] == "needs_reconciliation"
    rows["concurrent"] = {"id": "concurrent", "ext_ids": {"doi": "10.1234/new"}}
    second = batch_import_dois(client, "lib", ["10.1234/new"], authorized=True, dry_run=False)
    assert second["results"][0]["status"] == "needs_reconciliation"
    assert calls.count(("POST", "/collections/lib/items")) == 1


def test_journal_recovers_known_item_when_scan_is_behind(make_client, monkeypatch):
    client, rows, calls = client_setup(make_client)
    original_get = client.get_item
    failed = False

    def delayed(cid, iid):
        nonlocal failed
        if iid.startswith("item") and not failed:
            failed = True
            raise ProtocolError("readback unavailable")
        return original_get(cid, iid)

    monkeypatch.setattr(client, "get_item", delayed)
    first = batch_import_dois(client, "lib", ["10.1234/new"], authorized=True, dry_run=False)
    assert first["results"][0]["status"] == "needs_reconciliation"
    saved_item = first["results"][0]["item_id"]
    original_list = client.list_items
    monkeypatch.setattr(
        client,
        "list_items",
        lambda *a, **kw: [x for x in original_list(*a, **kw) if x["id"] != saved_item],
    )
    second = batch_import_dois(client, "lib", ["10.1234/new"], authorized=True, dry_run=False)
    assert second["results"][0]["status"] == "existing"
    assert second["results"][0]["verified"] and saved_item in rows
    assert calls.count(("POST", "/collections/lib/items")) == 1


def test_batch_checks_recent_single_import_when_index_is_behind(make_client, monkeypatch):
    from readcube_client import WriteAuthorization

    client, _, calls = client_setup(make_client)
    first = client.import_by_doi(
        "lib",
        "10.1234/new",
        authorization=WriteAuthorization(collection_id="lib", authorized=True),
        dry_run=False,
    )
    saved_item = first["item"]["id"]
    original_list = client.list_items
    monkeypatch.setattr(
        client,
        "list_items",
        lambda *a, **kw: [x for x in original_list(*a, **kw) if x["id"] != saved_item],
    )
    result = batch_import_dois(client, "lib", ["10.1234/new"], authorized=True, dry_run=False)
    assert result["results"][0]["status"] == "existing"
    assert calls.count(("POST", "/collections/lib/items")) == 1


def test_duplicate_doi_is_flagged_without_import(make_client):
    client, rows, calls = client_setup(make_client)
    rows["also"] = {"id": "also", "ext_ids": {"doi": "10.1234/old"}}
    result = batch_import_dois(client, "lib", ["10.1234/old"], authorized=True, dry_run=False)
    assert result["results"][0]["status"] == "needs_review"
    assert not any(method == "POST" for method, _ in calls)


def test_local_change_during_scan_prevents_batch_writes(make_client, monkeypatch):
    from readcube_client.workflow import _bump_generation

    client, _, calls = client_setup(make_client)
    original_list = client.list_items

    def changed(*args, **kwargs):
        rows = original_list(*args, **kwargs)
        _bump_generation(client, "lib")
        return rows

    monkeypatch.setattr(client, "list_items", changed)
    with pytest.raises(ProtocolError, match="changed during preflight"):
        batch_import_dois(client, "lib", ["10.1234/new"], authorized=True, dry_run=False)
    assert not any(method == "POST" for method, _ in calls)


def test_list_index_delay_does_not_repeat_membership_write(make_client):
    client, _, calls = client_setup(make_client, delay_list=True)
    first = batch_import_dois(
        client, "lib", ["10.1234/old"], list_id="list1", authorized=True, dry_run=False
    )
    assert first["stopped"] and first["results"][0]["list_status"] == "needs_reconciliation"
    second = batch_import_dois(
        client, "lib", ["10.1234/old"], list_id="list1", authorized=True, dry_run=False
    )
    assert second["stopped"] and second["results"][0]["list_status"] == "needs_reconciliation"
    assert calls.count(("POST", "/collections/lib/lists/list1/add_items")) == 1


def test_batch_checks_auth_and_verification_before_any_write(make_client):
    client, _, calls = client_setup(make_client)
    with pytest.raises(AuthorizationError):
        batch_import_dois(client, "lib", ["10.1234/new"], dry_run=False)
    assert not calls
    client.registry.records.pop("import_identifier")
    with pytest.raises(UnverifiedEndpointError):
        batch_import_dois(client, "lib", ["10.1234/new"], dry_run=False, authorized=True)
    assert not calls
