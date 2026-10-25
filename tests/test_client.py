import hashlib
import json
import logging
from pathlib import Path

import httpx
import pytest

from readcube_client import ReadCubeClient, Settings, WriteAuthorization, normalize_doi
from readcube_client.auth import load_cookies, private_json_write
from readcube_client.errors import (
    APIError,
    AuthenticationError,
    AuthorizationError,
    PaginationError,
    ProtocolError,
    UnverifiedEndpointError,
)
from readcube_client.research import ResearchClient


def item(item_id="paper1", doi="10.1234/test"):
    return {"id": item_id, "article": {"title": "Test"}, "ext_ids": {"doi": doi}, "user_data": {}}


def test_unverified_get_cannot_transmit(make_client):
    calls = []
    client = make_client(lambda request: calls.append(request))
    with pytest.raises(UnverifiedEndpointError):
        client.list_collections()
    assert calls == []


def test_unverified_annotation_cannot_execute(make_client):
    from readcube_client.annotations import PageNote

    client = make_client(
        lambda request: pytest.fail("No request permitted"), write_collections=["library"]
    )
    note = PageNote(sha256="a" * 64, page_start=0, position=(10, 20), note="test")
    plan = client.create_annotation("library", "paper", note)
    assert not plan.verified and plan.dry_run
    with pytest.raises(UnverifiedEndpointError, match="UNVERIFIED"):
        client.create_annotation(
            "library",
            "paper",
            note,
            authorization=WriteAuthorization(collection_id="library", authorized=True),
            dry_run=False,
        )


def test_dryrun_does_not_need_auth_or_verification(make_client):
    client = make_client(lambda request: pytest.fail("Dry-run transmitted a request"))
    plan = client.update_notes("library", "paper", "test")
    assert plan.dry_run and not plan.verified
    assert plan.body == {"notes": "test"}
    assert plan.evidence == "SOURCE_CONFIRMED"


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        WriteAuthorization(collection_id="library", authorized=False),
        WriteAuthorization(collection_id="other", authorized=True),
    ],
)
def test_write_requires_matching_human_authorization(make_client, authorization):
    client = make_client(
        lambda request: pytest.fail("Unauthorized write"),
        verified=["update_notes"],
        write_collections=["library"],
    )
    with pytest.raises(AuthorizationError):
        client.update_notes("library", "paper", "test", authorization=authorization, dry_run=False)


def test_collection_allowlist_is_independent_of_call_boolean(make_client):
    client = make_client(lambda request: pytest.fail("Not allowlisted"), verified=["update_notes"])
    with pytest.raises(AuthorizationError):
        client.update_notes(
            "library",
            "paper",
            "x",
            dry_run=False,
            authorization=WriteAuthorization(collection_id="library", authorized=True),
        )


def test_deletion_requires_separate_target_confirmation(make_client):
    client = make_client(
        lambda request: pytest.fail("Deletion was not separately confirmed"),
        verified=["delete_item"],
        write_collections=["library"],
    )
    with pytest.raises(AuthorizationError, match="Separate deletion"):
        client.delete_item(
            "library",
            "paper",
            dry_run=False,
            authorization=WriteAuthorization(collection_id="library", authorized=True),
        )


def test_successful_delete_request_uses_exact_target(make_client):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"item": {**item(), "deleted": True}})

    client = make_client(handler, verified=["delete_item"], write_collections=["library"])
    result = client.delete_item(
        "library",
        "paper1",
        dry_run=False,
        authorization=WriteAuthorization(
            collection_id="library", authorized=True, confirmation="DELETE paper1"
        ),
    )
    assert result["item"]["deleted"]
    assert len(calls) == 1 and calls[0].method == "DELETE"
    assert calls[0].url.path == "/collections/library/items/paper1"


def test_contract_change_revokes_verification(make_client):
    client = make_client(
        lambda request: pytest.fail("Changed contract"), verified=["list_collections"]
    )
    client.registry.catalog["list_collections"]["path"] = "/different"
    with pytest.raises(UnverifiedEndpointError):
        client.list_collections()


def test_verification_is_scoped_to_session(make_client, tmp_path):
    client = make_client(lambda request: pytest.fail("Wrong session"))
    private_json_write(
        tmp_path / "verified.json",
        {
            "session": "other-session",
            "operations": {
                "list_collections": {
                    "status": "VERIFIED",
                    "semantic_check": True,
                    "contract_sha256": client.registry.signature("list_collections"),
                }
            },
        },
    )
    other = ReadCubeClient(client.settings, http=client.http)
    assert not other.registry.verified("list_collections")


@pytest.mark.parametrize(
    "doi",
    [
        "10.1234/ABC",
        " https://doi.org/10.1234/ABC ",
        "doi:10.1234/abc",
        "https://dx.doi.org/10.1234/abc",
    ],
)
def test_doi_normalization(doi):
    assert normalize_doi(doi) == "10.1234/abc"


@pytest.mark.parametrize("doi", ["abc", "https://example.com/10.1234/a", "10.123/a", "10.1234/a b"])
def test_invalid_doi_rejected(doi):
    with pytest.raises(ValueError):
        normalize_doi(doi)


def test_scroll_cursor_may_stay_constant_while_results_advance(make_client):
    pages = [
        {"items": [item("a")], "scroll_id": "same", "total": 2},
        {"items": [item("b")], "scroll_id": "same", "total": 2},
        {"items": [], "scroll_id": "same", "total": 2},
    ]
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=pages.pop(0))

    client = make_client(handler, verified=["list_items"])
    assert [row["id"] for row in client.list_items("library", query="test")] == ["a", "b"]
    assert calls[0].url.params["query"] == "test"
    assert "query" not in calls[1].url.params
    assert calls[1].url.params["scroll_id"] == "same"


def test_stuck_scroll_does_not_overwrite_previous_snapshot(make_client):
    client = make_client(
        lambda request: httpx.Response(
            200, json={"items": [item()], "scroll_id": "stuck", "total": 50}
        ),
        verified=["list_items"],
    )
    snapshot = client.settings.state_dir / client.session / "library.json"
    private_json_write(snapshot, {"old": "hash"})
    with pytest.raises(PaginationError, match="Duplicate"):
        client.sync_changes("library")
    assert json.loads(snapshot.read_text()) == {"old": "hash"}


def test_missing_cursor_cannot_masquerade_as_complete_scan(make_client):
    client = make_client(
        lambda request: httpx.Response(200, json={"items": [item()], "total": 2}),
        verified=["list_items"],
    )
    with pytest.raises(PaginationError, match="Missing cursor"):
        client.list_items("library")


def test_shape_errors_are_explicit(make_client):
    client = make_client(
        lambda request: httpx.Response(200, json={"status": "ok", "items": "wrong"}),
        verified=["list_items"],
    )
    with pytest.raises(ProtocolError):
        client.list_items("library")


def test_rate_limit_retries_get_only(make_client, monkeypatch):
    calls = []
    sleeps = []
    monkeypatch.setattr("readcube_client.client.time.sleep", sleeps.append)

    def handler(request):
        calls.append(request)
        return (
            httpx.Response(429, headers={"Retry-After": "2"})
            if len(calls) == 1
            else httpx.Response(200, json={"collections": []})
        )

    client = make_client(handler, verified=["list_collections"])
    client.settings.retries = 2
    assert client.list_collections() == []
    assert len(calls) == 2 and sleeps == [2]


def test_long_retry_after_fails_without_retrying_early(make_client, monkeypatch):
    calls = []
    monkeypatch.setattr("readcube_client.client.time.sleep", lambda delay: pytest.fail("Long wait"))

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"})

    client = make_client(handler, verified=["list_collections"])
    client.settings.retries = 2
    with pytest.raises(APIError):
        client.list_collections()
    assert len(calls) == 1


def test_post_is_not_retried_even_on_server_error(make_client):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, json={"error": "private-sentinel"})

    client = make_client(handler, verified=["update_notes"], write_collections=["library"])
    client.settings.retries = 4
    with pytest.raises(APIError) as error:
        client.update_notes(
            "library",
            "paper",
            "notes",
            dry_run=False,
            authorization=WriteAuthorization(collection_id="library", authorized=True),
        )
    assert len(calls) == 1 and "private-sentinel" not in str(error.value)


@pytest.mark.parametrize("status", [401, 403])
def test_expired_session_does_not_retry_or_return_empty(make_client, status):
    client = make_client(
        lambda request: httpx.Response(status, json={"secret": "never-log"}),
        verified=["list_collections"],
    )
    with pytest.raises(AuthenticationError) as error:
        client.list_collections()
    assert "never-log" not in str(error.value)


def test_html_login_page_is_not_success(make_client):
    client = make_client(
        lambda request: httpx.Response(200, text="<html>login</html>"),
        verified=["list_collections"],
    )
    with pytest.raises(ProtocolError, match="expected JSON"):
        client.list_collections()


def test_business_error_is_not_empty_library(make_client):
    client = make_client(
        lambda request: httpx.Response(200, json={"status": "error", "collections": []}),
        verified=["list_collections"],
    )
    with pytest.raises(ProtocolError):
        client.list_collections()


def test_exact_doi_search_and_manual_review(make_client):
    client = make_client(
        lambda request: httpx.Response(
            200,
            json={
                "items": [item("a", "https://doi.org/10.1234/ABC"), item("b", "10.1234/abc-extra")]
            },
        ),
        verified=["list_items"],
    )
    assert [i["id"] for i in client.find_by_doi("doi:10.1234/abc", "library")] == ["a"]


def test_dedup_handles_indexing_delay_without_second_post(make_client):
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"item": item()})
        if request.url.path.endswith("/paper1"):
            return httpx.Response(200, json={"item": item()})
        return httpx.Response(200, json={"items": []})

    client = make_client(
        handler,
        verified=["import_identifier", "list_items", "get_item"],
        write_collections=["library"],
    )
    writes = {
        "dry_run": False,
        "authorization": WriteAuthorization(collection_id="library", authorized=True),
    }
    first = client.import_by_doi("library", "10.1234/test", **writes)
    second = client.import_by_doi("library", "10.1234/test", **writes)
    assert first["item"]["id"] == second["matches"][0]["id"]
    assert second["created"] is False
    assert sum(r.method == "POST" for r in calls) == 1


def test_pmid_has_its_own_verification_gate(make_client):
    client = make_client(
        lambda request: pytest.fail("PMID has not been verified"),
        verified=["import_identifier"],
        write_collections=["library"],
    )
    with pytest.raises(UnverifiedEndpointError, match="import_pmid"):
        client.import_by_pmid(
            "library",
            "123456",
            dry_run=False,
            authorization=WriteAuthorization(collection_id="library", authorized=True),
        )


def test_multiple_matches_request_manual_review_without_post(make_client):
    def handler(request):
        assert request.method == "GET"
        return httpx.Response(200, json={"items": [item("a"), item("b")]})

    client = make_client(
        handler, verified=["import_identifier", "list_items"], write_collections=["library"]
    )
    result = client.import_by_doi(
        "library",
        "10.1234/test",
        dry_run=False,
        authorization=WriteAuthorization(collection_id="library", authorized=True),
    )
    assert result["needs_review"] and not result["created"]


def test_pdf_dryrun_contains_hash_but_never_uploads(make_client, tmp_path):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(b"%PDF-1.4\nsynthetic")
    client = make_client(lambda request: pytest.fail("No upload during dry-run"))
    plan = client.upload_pdf("library", "paper", path)
    assert plan.dry_run and len(plan.body["hash"]) == 64
    assert "PUT" in plan.note


def test_pdf_root_enforced_before_read(make_client, tmp_path):
    path = tmp_path / "outside.pdf"
    path.write_bytes(b"%PDF-1.4")
    client = make_client(
        lambda request: pytest.fail("Forbidden file"), upload_roots=[tmp_path / "allowed"]
    )
    with pytest.raises(AuthorizationError):
        client.upload_pdf("library", "paper", path)


def test_private_cookie_file_and_domain_scope(tmp_path):
    path = tmp_path / "session.json"
    private_json_write(
        path,
        {
            "cookies": [
                {
                    "name": "x",
                    "value": "fake",
                    "domain": ".readcube.com",
                    "path": "/",
                    "secure": True,
                }
            ]
        },
    )
    assert path.stat().st_mode & 0o777 == 0o600
    cookies = load_cookies(path)
    calls = []
    with httpx.Client(
        cookies=cookies,
        transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200)),
    ) as client:
        client.get("https://sync.readcube.com/collections")
        client.get("https://example.com/")
    assert "x=fake" in calls[0].headers["cookie"]
    assert "cookie" not in calls[1].headers


def test_insecure_cookie_permissions_rejected(tmp_path):
    path = tmp_path / "session.json"
    path.write_text('{"cookies": []}')
    path.chmod(0o644)
    with pytest.raises(AuthenticationError, match="0600"):
        load_cookies(path)


def test_unknown_cookie_domain_rejected(tmp_path):
    path = tmp_path / "session.json"
    private_json_write(
        path, {"cookies": [{"name": "x", "value": "fake", "domain": "readcube.com.evil.org"}]}
    )
    with pytest.raises(AuthenticationError, match="unexpected"):
        load_cookies(path)


def test_research_cannot_self_promote_without_actual_request(tmp_path):
    settings = Settings(
        _env_file=None, session_file=tmp_path / "missing", verification_file=tmp_path / "ledger"
    )
    with (
        ResearchClient(settings, acknowledge_unverified=True) as client,
        pytest.raises(ProtocolError, match="actual successful request"),
    ):
        client.record_verified(
            "list_collections", semantic_check=True, detail="mock is not evidence"
        )


def test_environment_overrides_toml(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text("[readcube]\ntimeout=15\n")
    monkeypatch.setenv("READCUBE_TIMEOUT", "21")
    assert Settings.from_toml(path).timeout == 21


def test_resource_path_traversal_rejected(make_client):
    client = make_client(lambda request: pytest.fail("Invalid ID"), verified=["get_item"])
    with pytest.raises(ValueError, match="identifier"):
        client.get_item("../elsewhere", "paper")


def test_upload_s3_never_receives_session_or_logs_signature(
    make_client, tmp_path, monkeypatch, caplog
):
    path = tmp_path / "test.pdf"
    path.write_bytes(b"%PDF-1.4\nsynthetic transport test")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    remote_item = {**item(), "files": [{"hash": digest, "file_name": path.name}]}
    storage_calls = []
    main_calls = []

    def main_handler(request):
        main_calls.append(request)
        if request.url.path.endswith("/add_file"):
            if sum(r.url.path.endswith("/add_file") for r in main_calls) == 1:
                return httpx.Response(
                    200,
                    json={
                        "upload_id": "upload1",
                        "upload_url": "https://s3.amazonaws.com/bucket/pdf?Signature=never-log-this-signature",
                    },
                )
            return httpx.Response(200, json={"item": remote_item})
        if request.url.path.endswith("/uploads_pending"):
            return httpx.Response(200, json={"upload1": {"status": "completed", "hash": digest}})
        return httpx.Response(200, json={"item": remote_item})

    def storage_handler(request):
        storage_calls.append(request)
        return httpx.Response(200)

    caplog.set_level(logging.INFO)
    client = make_client(
        main_handler,
        verified=["add_file", "uploads_pending", "get_item", "upload_pdf_flow"],
        write_collections=["library"],
        upload_hosts=["s3.amazonaws.com"],
    )
    original_client = httpx.Client
    monkeypatch.setattr(
        "readcube_client.client.httpx.Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(storage_handler), **kwargs),
    )
    result = client.upload_pdf(
        "library",
        "paper1",
        path,
        dry_run=False,
        authorization=WriteAuthorization(collection_id="library", authorized=True),
    )
    assert result["associated"] is True
    assert len(storage_calls) == 1
    assert storage_calls[0].method == "PUT"
    assert storage_calls[0].content == path.read_bytes()
    assert "cookie" not in storage_calls[0].headers
    assert "never-log-this-signature" not in caplog.text
    assert len(main_calls) == 4


def test_upload_host_gate_stops_before_file_transmission(make_client, tmp_path, monkeypatch):
    path = tmp_path / "test.pdf"
    path.write_bytes(b"%PDF-1.4\nsynthetic")
    client = make_client(
        lambda request: httpx.Response(
            200, json={"upload_id": "x", "upload_url": "https://unexpected.example/pdf"}
        ),
        verified=["add_file", "uploads_pending", "get_item", "upload_pdf_flow"],
        write_collections=["library"],
    )
    monkeypatch.setattr(
        "readcube_client.client.httpx.Client",
        lambda **kwargs: pytest.fail("Unexpected destination received a request"),
    )
    with pytest.raises(AuthorizationError, match="hostname allowlist"):
        client.upload_pdf(
            "library",
            "paper",
            path,
            dry_run=False,
            authorization=WriteAuthorization(collection_id="library", authorized=True),
        )


def test_successful_scans_report_local_changes_and_missing_separately(make_client):
    scans = [[item("a"), item("b")], [{**item("a"), "article": {"title": "Changed"}}, item("c")]]
    client = make_client(
        lambda request: httpx.Response(200, json={"items": scans.pop(0)}), verified=["list_items"]
    )
    assert client.sync_changes("library").added == ["a", "b"]
    delta = client.sync_changes("library")
    assert delta.added == ["c"] and delta.changed == ["a"] and delta.missing == ["b"]
    assert delta.mode == "full_scan_local_diff"


def test_environment_tilde_paths_expand(monkeypatch):
    monkeypatch.setenv("READCUBE_SESSION_FILE", "~/.config/readcube-client/session.json")
    assert (
        Settings(_env_file=None).session_file
        == Path.home() / ".config/readcube-client/session.json"
    )
