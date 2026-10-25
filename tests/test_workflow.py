import json

import pytest

from readcube_client.errors import AuthorizationError, ProtocolError, UnverifiedEndpointError
from readcube_client.workflow import append_note, query_library, workflow_status


def verified_client(make_client, monkeypatch, *, allowed=True):
    client = make_client(
        lambda request: (_ for _ in ()).throw(AssertionError("Unexpected transport request")),
        verified=("list_items", "get_item", "update_notes"),
        write_collections=["lib"] if allowed else [],
    )
    monkeypatch.setattr(client, "close", lambda: None)
    return client


def test_cached_queries_counts_filters_and_exact_doi(make_client, monkeypatch):
    client = verified_client(make_client, monkeypatch)
    calls = []
    items = [
        {
            "id": "a",
            "article": {"title": "First human study", "year": 2007},
            "ext_ids": {"doi": "10.1000/a"},
            "user_data": {
                "unread": False,
                "last_read": "2026-10-25T00:00:00Z",
                "has_annotations": True,
                "notes": "NEST-1 808",
                "tags": ["clinical"],
            },
        },
        {"id": "b", "article": {"title": "Other"}, "user_data": {"unread": True}},
        {"id": "c", "article": {"title": "No status"}},
        {"id": "d", "article": {"title": "Deleted"}, "deleted": True},
    ]
    monkeypatch.setattr(client, "list_items", lambda cid: calls.append(cid) or items)
    first = query_library(client, "lib", limit=1)
    assert first["source"] == "live_full_scan"
    assert first["total"] == 3 and first["marked_read"] == 1
    assert first["truncated"] and first["matched"] == 3
    second = query_library(client, "lib", field="notes", query="nest-1", read_only=True)
    assert second["source"] == "cache" and second["matched"] == 1
    assert second["as_of"] == first["as_of"] and calls == ["lib"]
    assert (
        query_library(client, "lib", field="doi", query="https://doi.org/10.1000/A")["matched"] == 1
    )
    assert query_library(client, "lib", field="doi", query="10.1000/ab")["matched"] == 0
    assert query_library(client, "lib", annotated_only=True)["matched"] == 1
    assert query_library(client, "lib", field="tags", query="clinical")["matched"] == 1
    query_library(client, "lib", refresh=True)
    assert calls == ["lib", "lib"]


def test_cache_session_verification_expiry_and_failed_refresh(make_client, monkeypatch):
    client = verified_client(make_client, monkeypatch)
    monkeypatch.setattr(client, "list_items", lambda cid: [{"id": "a"}])
    query_library(client, "lib")
    path = next((client.settings.state_dir / "library-index").glob("*.json"))
    saved = path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    client.registry.records.clear()
    with pytest.raises(UnverifiedEndpointError):
        query_library(client, "lib")
    for op in ("list_items",):
        client.registry.records[op] = {
            "status": "VERIFIED",
            "semantic_check": True,
            "contract_sha256": client.registry.signature(op),
        }

    def failed(cid):
        raise ProtocolError("incomplete scan")

    monkeypatch.setattr(client, "list_items", failed)
    with pytest.raises(ProtocolError):
        query_library(client, "lib", refresh=True)
    assert path.read_text() == saved
    stale = json.loads(saved)
    stale["fetched_at"] = 0
    path.write_text(json.dumps(stale))
    with pytest.raises(ProtocolError):
        query_library(client, "lib")
    client.session = "different-session"
    with pytest.raises(ProtocolError):
        query_library(client, "lib")


def test_permission_preflight_stops_before_network(make_client, monkeypatch):
    client = verified_client(make_client, monkeypatch, allowed=False)
    assert workflow_status(client, "lib")["write_allowed"] is False
    monkeypatch.setattr(
        client, "get_item", lambda *a: pytest.fail("No read before permission check")
    )
    with pytest.raises(AuthorizationError):
        append_note(client, "lib", "a", "marker", authorized=True, dry_run=False)


def test_append_preserves_notes_plans_verifies_and_is_idempotent(make_client, monkeypatch):
    client = verified_client(make_client, monkeypatch)
    state = {"notes": "existing  \n", "writes": 0}
    events = []

    def get(cid, iid):
        events.append("get")
        return {"id": iid, "article": {"title": "Study"}, "user_data": {"notes": state["notes"]}}

    original = client.update_notes

    def update(cid, iid, notes, **kwargs):
        events.append("plan" if kwargs.get("dry_run") else "write")
        if kwargs.get("dry_run"):
            return original(cid, iid, notes, **kwargs)
        state["notes"] = notes
        state["writes"] += 1

    monkeypatch.setattr(client, "get_item", get)
    monkeypatch.setattr(client, "update_notes", update)
    monkeypatch.setattr(client, "list_items", lambda cid: [{"id": "a"}])
    query_library(client, "lib")
    planned = append_note(client, "lib", "a", "marker")
    assert planned["dry_run"] and state["writes"] == 0
    assert not planned["verified"] and planned["plan"]["verified"]
    events.clear()
    result = append_note(client, "lib", "a", "marker", authorized=True, dry_run=False)
    assert result["verified"] and result["changed"]
    assert state["notes"] == "existing  \nmarker"
    assert events == ["get", "write", "get"]
    cached = query_library(client, "lib", field="notes", query="marker")
    assert cached["source"] == "cache" and cached["matched"] == 1
    again = append_note(client, "lib", "a", "marker", authorized=True, dry_run=False)
    assert not again["changed"] and state["writes"] == 1


def test_readback_mismatch_is_failure(make_client, monkeypatch):
    client = verified_client(make_client, monkeypatch)
    monkeypatch.setattr(client, "get_item", lambda *a: {"user_data": {"notes": "old"}})
    original = client.update_notes
    monkeypatch.setattr(
        client, "update_notes", lambda *a, **kw: original(*a, **kw) if kw.get("dry_run") else None
    )
    with pytest.raises(ProtocolError, match="read-back"):
        append_note(client, "lib", "a", "new", authorized=True, dry_run=False)


def test_mcp_workflows_share_cache_and_report_preflight(make_client, monkeypatch):
    import asyncio

    from readcube_mcp.server import create_server

    client = verified_client(make_client, monkeypatch)
    calls = []
    monkeypatch.setattr(client, "list_items", lambda cid: calls.append(cid) or [{"id": "a"}])
    server = create_server(lambda: client)

    async def check():
        tools = {t.name: t for t in await server.list_tools()}
        assert tools["readcube_append_note"].input_schema["properties"]["dry_run"]["default"]
        assert not tools["readcube_append_note"].input_schema["properties"]["authorized"]["default"]
        status = await server.call_tool("readcube_workflow_status", {"collection_id": "lib"})
        assert status.structured_content["write_allowed"]
        args = {"collection_id": "lib"}
        await server.call_tool("readcube_query_library", args)
        second = await server.call_tool("readcube_query_library", args)
        assert second.structured_content["source"] == "cache" and calls == ["lib"]

    asyncio.run(check())


def test_shared_raw_snapshot_preserves_provenance_and_detaches_results(make_client, monkeypatch):
    from readcube_client.workflow import cached_library_items, patch_library_cache

    client = verified_client(make_client, monkeypatch)
    original_item = {
        "id": "a",
        "extra_server_field": {"anything": 42},
        "user_data": {"notes": "old", "tags": ["tag"]},
    }
    scans = []
    monkeypatch.setattr(client, "list_items", lambda cid: scans.append(cid) or [original_item])
    first = query_library(client, "lib")
    raw, metadata = cached_library_items(client, "lib")
    assert metadata["source"] == "cache" and metadata["as_of"] == first["as_of"]
    assert raw[0]["extra_server_field"] == {"anything": 42}
    raw[0]["user_data"]["notes"] = "caller mutation"
    first["items"][0]["tags"].append("caller mutation")
    patch_library_cache(client, "lib", "a", user_data_patch={"notes": "new"})
    current, after = cached_library_items(client, "lib")
    assert current[0]["user_data"] == {"notes": "new", "tags": ["tag"]}
    assert after["as_of"] == metadata["as_of"] and scans == ["lib"]
    patch_library_cache(client, "lib", "unknown", user_data_patch={"notes": "new"})
    assert not list((client.settings.state_dir / "library-index").glob("*.json"))


def test_compact_notes_are_bounded_but_searches_use_full_text(make_client, monkeypatch):
    from readcube_client.workflow import cached_library_items

    client = verified_client(make_client, monkeypatch)
    text = "x" * 10000 + "needle"
    monkeypatch.setattr(
        client,
        "list_items",
        lambda cid: [
            {"id": "a", "user_data": {"notes": text}},
        ],
    )
    result = query_library(client, "lib", query="needle", field="notes")
    assert result["matched"] == 1 and result["items"][0]["notes_truncated"]
    assert len(result["items"][0]["notes"]) == 320
    raw, _ = cached_library_items(client, "lib")
    assert raw[0]["user_data"]["notes"] == text


def test_invalid_doi_and_collection_fail_before_scan(make_client, monkeypatch):
    client = verified_client(make_client, monkeypatch)
    monkeypatch.setattr(client, "list_items", lambda *a: pytest.fail("Invalid query must not scan"))
    with pytest.raises(ValueError):
        query_library(client, "lib", field="doi", query="not-a-doi")
    with pytest.raises(ValueError):
        query_library(client, "../../lib")


def test_concurrent_cold_queries_scan_once_and_notes_append_without_lost_updates(
    make_client, monkeypatch
):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    client = verified_client(make_client, monkeypatch)
    other = verified_client(make_client, monkeypatch)
    scans = []
    state = {"notes": "original"}
    barrier = threading.Barrier(2)

    def scan(cid):
        scans.append(cid)
        time.sleep(0.05)
        return [{"id": "a", "user_data": {"notes": state["notes"]}}]

    for current in (client, other):
        monkeypatch.setattr(current, "list_items", scan)

    def query(current):
        barrier.wait(timeout=2)
        return query_library(current, "lib")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(query, [client, other]))
    assert scans == ["lib"]
    assert {first["source"], second["source"]} == {"live_full_scan", "cache"}

    def get(cid, iid):
        value = state["notes"]
        time.sleep(0.02)
        return {"id": iid, "user_data": {"notes": value}}

    def update(cid, iid, notes, **kw):
        assert kw["dry_run"] is False
        state["notes"] = notes

    for current in (client, other):
        monkeypatch.setattr(current, "get_item", get)
        monkeypatch.setattr(current, "update_notes", update)

    def append(args):
        current, text = args
        barrier.wait(timeout=2)
        return append_note(current, "lib", "a", text, authorized=True, dry_run=False)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(append, [(client, "one"), (other, "two")]))
    assert all(result["verified"] for result in results)
    assert set(state["notes"].splitlines()) == {"original", "one", "two"}
    assert query_library(client, "lib", field="notes", query="two")["matched"] == 1
    assert query_library(other, "lib", field="notes", query="one")["matched"] == 1
    assert scans == ["lib"]


def test_failed_note_write_invalidates_complete_snapshot(make_client, monkeypatch):
    from readcube_client.errors import TransportError

    client = verified_client(make_client, monkeypatch)
    monkeypatch.setattr(client, "list_items", lambda cid: [{"id": "a"}])
    query_library(client, "lib")
    monkeypatch.setattr(client, "get_item", lambda *a: {"id": "a", "user_data": {"notes": ""}})

    def fail(*args, **kwargs):
        raise TransportError("Response lost")

    monkeypatch.setattr(client, "update_notes", fail)
    with pytest.raises(TransportError):
        append_note(client, "lib", "a", "marker", authorized=True, dry_run=False)
    assert not list((client.settings.state_dir / "library-index").glob("*.json"))


def test_external_cache_replacement_and_corruption_never_reuse_stale_memory(
    make_client, monkeypatch
):
    from readcube_client.workflow import _atomic_json

    client = verified_client(make_client, monkeypatch)
    calls = []
    monkeypatch.setattr(client, "list_items", lambda cid: calls.append(cid) or [{"id": "a"}])
    query_library(client, "lib")
    path = next((client.settings.state_dir / "library-index").glob("*.json"))
    replacement = json.loads(path.read_text())
    replacement["raw_items"][0]["user_data"] = {"notes": "external"}
    replacement["items"][0]["notes"] = "external"
    _atomic_json(path, replacement)
    assert query_library(client, "lib", field="notes", query="external")["matched"] == 1
    _atomic_json(path, {"version": 2, "items": "corrupt"})
    result = query_library(client, "lib")
    assert result["source"] == "live_full_scan" and calls == ["lib", "lib"]


def test_note_does_not_wait_for_cold_scan_and_scan_cannot_overwrite_it(make_client, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    client = verified_client(make_client, monkeypatch)
    writer = verified_client(make_client, monkeypatch)
    scan_started, release_scan = threading.Event(), threading.Event()
    state = {"notes": "old", "scans": 0}

    def scan(cid):
        state["scans"] += 1
        item = {"id": "a", "user_data": {"notes": state["notes"]}}
        if state["scans"] == 1:
            scan_started.set()
            assert release_scan.wait(timeout=3)
        return [item]

    def get(cid, iid):
        return {"id": iid, "user_data": {"notes": state["notes"]}}

    def update(cid, iid, notes, **kwargs):
        state["notes"] = notes

    monkeypatch.setattr(client, "list_items", scan)
    monkeypatch.setattr(writer, "get_item", get)
    monkeypatch.setattr(writer, "update_notes", update)
    with ThreadPoolExecutor(max_workers=2) as pool:
        query = pool.submit(query_library, client, "lib")
        assert scan_started.wait(timeout=2)
        note = pool.submit(append_note, writer, "lib", "a", "new", authorized=True, dry_run=False)
        try:
            # If a full scan held the cache lock, this would block until release_scan.
            assert note.result(timeout=1)["verified"]
        finally:
            release_scan.set()
        result = query.result(timeout=3)
    assert state["scans"] == 2
    assert result["items"][0]["notes"] == "old\nnew"
    assert query_library(client, "lib")["items"][0]["notes"] == "old\nnew"


def test_repeated_concurrent_mutations_do_not_publish_inconsistent_scan(make_client, monkeypatch):
    from readcube_client.workflow import invalidate_library_cache

    client = verified_client(make_client, monkeypatch)
    scans = []

    def scan(cid):
        scans.append(cid)
        invalidate_library_cache(client, cid)
        return [{"id": "a"}]

    monkeypatch.setattr(client, "list_items", scan)
    with pytest.raises(ProtocolError, match="both scans"):
        query_library(client, "lib")
    assert scans == ["lib", "lib"]
    assert not list((client.settings.state_dir / "library-index").glob("*.json"))


def test_append_readback_restores_snapshot_after_minimal_write_envelope(make_client, monkeypatch):
    from readcube_client.workflow import invalidate_library_cache

    client = verified_client(make_client, monkeypatch)
    state = {"notes": "old"}
    scans = []
    monkeypatch.setattr(
        client,
        "list_items",
        lambda cid: (
            scans.append(cid)
            or [
                {"id": "a", "user_data": {"notes": state["notes"]}},
                {"id": "b", "article": {"title": "Preserved"}},
            ]
        ),
    )
    initial = query_library(client, "lib")
    monkeypatch.setattr(
        client,
        "get_item",
        lambda cid, iid: {
            "id": iid,
            "user_data": {"notes": state["notes"]},
        },
    )

    def write(cid, iid, notes, **kwargs):
        state["notes"] = notes
        invalidate_library_cache(client, cid)
        return {"status": "ok"}

    monkeypatch.setattr(client, "update_notes", write)
    result = append_note(client, "lib", "a", "new", authorized=True, dry_run=False)
    cached = query_library(client, "lib", field="notes", query="new")
    assert result["verified"]
    assert cached["source"] == "cache" and cached["matched"] == 1 and cached["total"] == 2
    assert cached["as_of"] == initial["as_of"] and scans == ["lib"]
