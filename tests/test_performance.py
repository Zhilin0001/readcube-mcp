"""Request-count and cache-coherence regressions for latency-sensitive paths."""

import httpx
import pytest

from readcube_client import WriteAuthorization
from readcube_client.errors import PaginationError, ProtocolError, TransportError
from readcube_client.workflow import query_library


def test_count_reads_exactly_one_page(make_client):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"items": [{"id": "a"}], "total": 419, "scroll_id": "c"})

    client = make_client(handle, verified=["list_items"])
    assert client.count_items("lib")["total"] == 419
    assert len(requests) == 1 and requests[0].url.params["size"] == "1"


@pytest.mark.parametrize("total", [True, -1, "419", None])
def test_count_rejects_ambiguous_totals(make_client, total):
    client = make_client(
        lambda r: httpx.Response(200, json={"items": [], "total": total}), verified=["list_items"]
    )
    with pytest.raises(ProtocolError):
        client.count_items("lib")


def test_pagination_stops_at_total_without_terminal_request(make_client):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200, json={"items": [{"id": str(len(requests))}], "total": 2, "scroll_id": "same"}
        )

    client = make_client(handle, verified=["list_items"])
    assert len(client.list_items("lib")) == 2
    assert len(requests) == 2


def test_pagination_rejects_changed_total(make_client):
    replies = iter(
        [
            {"items": [{"id": "a"}], "total": 3, "scroll_id": "c"},
            {"items": [{"id": "b"}], "total": 2, "scroll_id": "c"},
        ]
    )
    client = make_client(
        lambda r: httpx.Response(200, json=next(replies)),
        verified=["list_items"],
        pagination_retries=0,
    )
    with pytest.raises(PaginationError, match="changed"):
        client.list_items("lib")


@pytest.mark.parametrize("failure", ["changed", "missing_cursor", "duplicate"])
def test_pagination_restarts_and_discards_partial_attempt(make_client, monkeypatch, failure):
    monkeypatch.setattr("readcube_client.client.time.sleep", lambda _: None)
    calls = []
    attempts = 0

    def handle(request):
        nonlocal attempts
        calls.append(request)
        if "scroll_id" not in request.url.params:
            attempts += 1
            if attempts == 1 and failure == "missing_cursor":
                return httpx.Response(200, json={"items": [{"id": "stale"}], "total": 2})
            first_id = "stale" if attempts == 1 else "fresh1"
            return httpx.Response(
                200, json={"items": [{"id": first_id}], "total": 2, "scroll_id": "cursor"}
            )
        if attempts == 1:
            item_id = "stale" if failure == "duplicate" else "other"
            total = 3 if failure == "changed" else 2
        else:
            item_id, total = "fresh2", 2
        return httpx.Response(200, json={"items": [{"id": item_id}], "total": total})

    client = make_client(handle, verified=["list_items"])
    iterator = client.iter_items("lib")
    assert next(iterator)["id"] == "fresh1"
    assert [row["id"] for row in iterator] == ["fresh2"]
    assert attempts == 2
    assert sum("scroll_id" not in request.url.params for request in calls) == 2


def test_import_refuses_write_after_persistent_incomplete_scans(make_client, monkeypatch):
    monkeypatch.setattr("readcube_client.client.time.sleep", lambda _: None)
    methods = []

    def handle(request):
        methods.append(request.method)
        return httpx.Response(200, json={"items": [{"id": "partial"}], "total": 2})

    client = make_client(
        handle,
        verified=["list_items", "import_identifier"],
        write_collections=["lib"],
    )
    with pytest.raises(PaginationError, match="failed after 3 attempts"):
        client.import_by_doi(
            "lib",
            "10.1234/test",
            authorization=WriteAuthorization(collection_id="lib", authorized=True),
            dry_run=False,
        )
    assert methods == ["GET", "GET", "GET"]


def test_legacy_search_shares_index_but_import_search_stays_live(make_client):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "a",
                        "article": {"title": "Human test"},
                        "ext_ids": {"doi": "10.1234/test"},
                    }
                ],
                "total": 1,
            },
        )

    client = make_client(handle, verified=["list_items"])
    first = client.cached_search("test", collection_id="lib")
    assert first[0]["_readcube_cache"]["source"] == "live_full_scan"
    assert query_library(client, "lib", query="human")["matched"] == 1
    assert client.cached_search("10.1234/test", field="doi", collection_id="lib")
    assert len(requests) == 1
    client.search("test", collection_id="lib")
    assert len(requests) == 2


@pytest.mark.parametrize("fail", [False, True])
def test_direct_note_write_updates_or_invalidates_cached_search(make_client, fail):
    requests = []
    state = {"notes": "before"}

    def handle(request):
        requests.append(request.method)
        if request.method != "GET":
            if fail:
                raise httpx.ReadTimeout("private diagnostic")
            state["notes"] = "after"
            return httpx.Response(200, json={"item": {"id": "a", "user_data": state.copy()}})
        return httpx.Response(
            200, json={"items": [{"id": "a", "user_data": state.copy()}], "total": 1}
        )

    client = make_client(handle, verified=["list_items", "update_notes"], write_collections=["lib"])
    first = query_library(client, "lib")
    kwargs = {
        "authorization": WriteAuthorization(collection_id="lib", authorized=True),
        "dry_run": False,
    }
    if fail:
        with pytest.raises(TransportError):
            client.update_notes("lib", "a", "after", **kwargs)
    else:
        client.update_notes("lib", "a", "after", **kwargs)
    after = query_library(client, "lib", query="after", field="notes")
    assert after["source"] == ("live_full_scan" if fail else "cache")
    assert after["matched"] == (0 if fail else 1)
    if not fail:
        assert after["as_of"] == first["as_of"]
        assert requests == ["GET", "POST"]


def test_sync_refreshes_query_index_without_a_second_full_scan(make_client):
    requests = []
    state = {"title": "before"}

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200, json={"items": [{"id": "a", "article": state.copy()}], "total": 1}
        )

    client = make_client(handle, verified=["list_items"])
    query_library(client, "lib")
    state["title"] = "after"
    assert client.sync_changes("lib").total == 1
    after = query_library(client, "lib", query="after")
    assert after["source"] == "cache" and after["matched"] == 1
    assert len(requests) == 2


def test_unconfirmed_note_response_cannot_poison_query_cache(make_client):
    calls = []

    def handle(request):
        calls.append(request.method)
        if request.method == "POST":
            return httpx.Response(200, json={"item": {"id": "a"}})
        return httpx.Response(
            200, json={"items": [{"id": "a", "user_data": {"notes": "actual"}}], "total": 1}
        )

    client = make_client(handle, verified=["list_items", "update_notes"], write_collections=["lib"])
    query_library(client, "lib")
    client.update_notes(
        "lib",
        "a",
        "requested",
        dry_run=False,
        authorization=WriteAuthorization(collection_id="lib", authorized=True),
    )
    result = query_library(client, "lib", field="notes", query="requested")
    assert result["source"] == "live_full_scan" and result["matched"] == 0
    assert calls == ["GET", "POST", "GET"]
