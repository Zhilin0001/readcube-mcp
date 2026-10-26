import copy
import json

import httpx
import pytest

from readcube_client.errors import AuthorizationError
from readcube_client.metadata import batch_update_metadata


def setup(make_client):
    rows = {
        i: {
            "id": i,
            "article": {"title": "Original", "authors": ["A. Author"], "journal": "Keep me"},
            "user_data": {"notes": "Keep notes", "tags": ["keep"]},
            "list_ids": ["folder"],
            "files": [{"sha256": "a" * 64}],
        }
        for i in ["a", "b"]
    }
    writes = []

    def handler(r):
        if r.url.path == "/collections":
            return httpx.Response(
                200, json={"collections": [{"id": "lib", "user": {"can_manage_item": True}}]}
            )
        iid = r.url.path.rsplit("/", 1)[-1]
        if r.method == "PATCH":
            body = json.loads(r.content)["item"]
            writes.append((iid, body))
            rows[iid].update(body)
        return httpx.Response(200, json={"item": copy.deepcopy(rows[iid])})

    client = make_client(
        handler,
        verified=("list_collections", "get_item", "update_metadata"),
        write_collections=["lib"],
    )
    return client, rows, writes


def test_metadata_batch_preserves_unpatched_fields_and_has_backup(make_client):
    client, rows, writes = setup(make_client)
    updates = [
        {"item_id": "a", "patch": {"article": {"title": "Changed"}}},
        {"item_id": "b", "patch": {"ext_ids": {"doi": "https://doi.org/10.1000/X"}}},
    ]
    preview = batch_update_metadata(client, "lib", updates)
    assert preview["dry_run"] and writes == []
    result = batch_update_metadata(client, "lib", updates, authorized=True, dry_run=False)
    assert result["verified"] and len(writes) == 2
    assert rows["a"]["article"]["journal"] == "Keep me"
    assert rows["a"]["user_data"]["notes"] == "Keep notes" and rows["a"]["list_ids"] == ["folder"]
    assert rows["b"]["ext_ids"]["doi"] == "10.1000/x"
    with open(result["journal_path"]) as stream:
        journal = json.load(stream)
    assert journal["before"]["a"]["article"]["title"] == "Original"


def test_metadata_batch_auth_and_full_validation_before_any_write(make_client):
    client, _, writes = setup(make_client)
    valid = {"item_id": "a", "patch": {"article": {"year": 2025}}}
    with pytest.raises(AuthorizationError):
        batch_update_metadata(client, "lib", [valid], dry_run=False)
    with pytest.raises(ValueError):
        batch_update_metadata(
            client,
            "lib",
            [valid, {"item_id": "b", "patch": {"files": []}}],
            authorized=True,
            dry_run=False,
        )
    with pytest.raises(ValueError):
        batch_update_metadata(client, "lib", [valid, valid], authorized=True, dry_run=False)
    assert writes == []


def test_uncertain_metadata_write_stops_and_is_not_retried(make_client, monkeypatch):
    client, _, writes = setup(make_client)
    original = client.get_item
    reads = 0

    def get(cid, iid):
        nonlocal reads
        reads += 1
        row = original(cid, iid)
        if reads > 2:
            row["article"]["title"] = "Concurrent mismatch"
        return row

    monkeypatch.setattr(client, "get_item", get)
    updates = [{"item_id": i, "patch": {"article": {"title": "Changed"}}} for i in ["a", "b"]]
    result = batch_update_metadata(client, "lib", updates, authorized=True, dry_run=False)
    assert not result["verified"] and len(writes) == 1
    assert [r["status"] for r in result["results"]] == ["needs_reconciliation", "not_attempted"]
