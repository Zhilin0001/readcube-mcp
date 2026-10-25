"""Regression coverage for extended endpoints and PDF import safety boundaries."""

import hashlib

import httpx
import pytest

from readcube_client import WriteAuthorization
from readcube_client.errors import AuthorizationError, ProtocolError, UnverifiedEndpointError
from readcube_client.models import WritePlan

IMPORT_VERIFIED = ["upload_file", "import_pdf_flow", "uploads_pending", "get_item", "list_items"]
AUTH = WriteAuthorization(collection_id="library", authorized=True)


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(b"%PDF-1.4\nsynthetic isolated test\n%%EOF")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def paper(item_id, digest=None, **extra):
    return {
        "id": item_id,
        "collection_id": "library",
        "files": [{"sha256": digest}] if digest else [],
        **extra,
    }


def test_import_pdf_dry_run_needs_no_network_or_verified_flow(make_client, pdf):
    path, digest = pdf
    client = make_client(lambda request: pytest.fail("dry-run made network request"))
    plan = client.import_pdf("library", path)
    assert isinstance(plan, WritePlan)
    assert plan.operation == "upload_file"
    assert plan.body["hash"] == digest
    assert plan.body["resolve"] is True
    assert plan.verified is False


def test_import_pdf_requires_flow_not_only_initialization_endpoint(make_client, pdf):
    client = make_client(
        lambda request: pytest.fail("unverified flow made a request"),
        verified=["upload_file"],
        write_collections=["library"],
    )
    with pytest.raises(UnverifiedEndpointError, match="import_pdf_flow"):
        client.import_pdf("library", pdf[0], dry_run=False, authorization=AUTH)


def test_import_pdf_rejects_unauthorized_collection_before_any_request(make_client, pdf):
    client = make_client(
        lambda request: pytest.fail("unauthorized import made a request"),
        verified=IMPORT_VERIFIED,
        write_collections=["other-library"],
    )
    with pytest.raises(AuthorizationError):
        client.import_pdf("library", pdf[0], dry_run=False, authorization=AUTH)


def test_import_pdf_rejects_file_outside_configured_roots(make_client, pdf, tmp_path):
    client = make_client(
        lambda request: pytest.fail("out-of-scope file caused network request"),
        verified=IMPORT_VERIFIED,
        write_collections=["library"],
        upload_roots=[tmp_path / "allowed"],
    )
    with pytest.raises(AuthorizationError, match="outside"):
        client.import_pdf("library", pdf[0], dry_run=False, authorization=AUTH)


@pytest.mark.parametrize("hash_field", ["sha256", "hash", "primary_file_hash"])
def test_import_pdf_reuses_existing_hash_without_writing(make_client, pdf, hash_field):
    path, digest = pdf
    row = paper("existing")
    if hash_field == "primary_file_hash":
        row[hash_field] = digest
    else:
        row["files"] = [{hash_field: digest}]
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.url.path == "/collections/library/items"
        return httpx.Response(200, json={"items": [row]})

    client = make_client(handler, verified=IMPORT_VERIFIED, write_collections=["library"])
    result = client.import_pdf("library", path, authorization=AUTH, dry_run=False)
    assert result["created"] is False
    assert result["item"]["id"] == "existing"
    assert result["needs_review"] is False
    assert len(calls) == 1


def test_import_pdf_multiple_hash_matches_require_review_without_writing(make_client, pdf):
    path, digest = pdf

    def handler(request):
        assert request.method == "GET"
        return httpx.Response(200, json={"items": [paper("a", digest), paper("b", digest)]})

    client = make_client(handler, verified=IMPORT_VERIFIED, write_collections=["library"])
    result = client.import_pdf("library", path, authorization=AUTH, dry_run=False)
    assert result["needs_review"] is True
    assert result["created"] is False
    assert "item" not in result
    assert {row["id"] for row in result["matches"]} == {"a", "b"}


def test_import_pdf_stale_recent_id_falls_back_to_library_scan(make_client, pdf):
    path, digest = pdf
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET", "stale cache must not cause a duplicate import"
        if request.url.path.endswith("/old"):
            return httpx.Response(200, json={"item": paper("old", "f" * 64)})
        return httpx.Response(200, json={"items": [paper("existing", digest)]})

    client = make_client(handler, verified=IMPORT_VERIFIED, write_collections=["library"])
    client._recent_pdf_imports[("library", digest)] = "old"
    result = client.import_pdf("library", path, authorization=AUTH, dry_run=False)
    assert result["created"] is False
    assert result["item"]["id"] == "existing"
    assert len(calls) == 2


def test_import_pdf_deleted_recent_item_does_not_hide_live_match(make_client, pdf):
    path, digest = pdf

    def handler(request):
        assert request.method == "GET", "live duplicate must not create another item"
        if request.url.path.endswith("/deleted"):
            return httpx.Response(200, json={"item": paper("deleted", digest, deleted=True)})
        return httpx.Response(200, json={"items": [paper("live", digest)]})

    client = make_client(handler, verified=IMPORT_VERIFIED, write_collections=["library"])
    client._recent_pdf_imports[("library", digest)] = "deleted"
    result = client.import_pdf("library", path, authorization=AUTH, dry_run=False)
    assert result["item"]["id"] == "live"
    assert result["created"] is False


def test_reader_metadata_normalizes_doi_and_checks_echo(make_client):
    def handler(request):
        assert request.url.params["doi"] == "10.1000/example"
        return httpx.Response(200, json={"meta": {"doi": "10.1000/example", "title": "Test"}})

    client = make_client(handler, verified=["reader_metadata"])
    assert client.reader_metadata("https://doi.org/10.1000/EXAMPLE")["meta"]["title"] == "Test"


@pytest.mark.parametrize(
    "meta", [{}, {"doi": None}, {"doi": 42}, {"doi": "not-a-doi"}, {"doi": "10.1000/wrong"}]
)
def test_reader_metadata_bad_doi_is_protocol_error(make_client, meta):
    client = make_client(
        lambda request: httpx.Response(200, json={"meta": meta}), verified=["reader_metadata"]
    )
    with pytest.raises(ProtocolError):
        client.reader_metadata("10.1000/example")


@pytest.mark.parametrize("rows", [None, {}, ["bad-revision"]])
def test_revisions_rejects_wrong_shape(make_client, rows):
    client = make_client(
        lambda request: httpx.Response(200, json={"revisions": rows}), verified=["get_revisions"]
    )
    with pytest.raises(ProtocolError):
        client.get_revisions("library", "paper")


@pytest.mark.parametrize("method", ["create_smartlist", "update_smartlist"])
@pytest.mark.parametrize("response", [[], "bad", None])
def test_smartlist_mutations_reject_non_object_response(make_client, method, response):
    client = make_client(
        lambda request: httpx.Response(200, json={"smartlist": response}),
        verified=[method],
        write_collections=["library"],
    )
    with pytest.raises(ProtocolError):
        if method == "create_smartlist":
            client.create_smartlist(
                "library", "Test", "tag:test", authorization=AUTH, dry_run=False
            )
        else:
            client.update_smartlist(
                "library", "smart", name="Renamed", authorization=AUTH, dry_run=False
            )


def test_smartlist_delete_still_requires_separate_confirmation(make_client):
    client = make_client(
        lambda request: pytest.fail("unconfirmed deletion transmitted"),
        verified=["delete_smartlist"],
        write_collections=["library"],
    )
    with pytest.raises(AuthorizationError, match="Separate deletion"):
        client.delete_smartlist("library", "smart", authorization=AUTH, dry_run=False)


def test_import_pdf_persistent_recent_id_survives_new_client(make_client, pdf):
    path, digest = pdf
    client1 = make_client(
        lambda request: httpx.Response(200, json={"items": [paper("existing", digest)]}),
        verified=IMPORT_VERIFIED,
        write_collections=["library"],
    )
    first = client1.import_pdf("library", path, authorization=AUTH, dry_run=False)
    assert first["created"] is False
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.url.path.endswith("/existing"), "cross-client cache should confirm by ID"
        return httpx.Response(200, json={"item": paper("existing", digest)})

    client2 = make_client(handler, verified=IMPORT_VERIFIED, write_collections=["library"])
    assert not client2._recent_pdf_imports
    second = client2.import_pdf("library", path, authorization=AUTH, dry_run=False)
    assert second["created"] is False
    assert second["item"]["id"] == "existing"
    assert len(calls) == 1
    cache = client2.settings.state_dir / client2.session / "pdf-imports-library.json"
    assert cache.stat().st_mode & 0o777 == 0o600


def test_import_pdf_missing_recent_id_falls_back_without_writing(make_client, pdf):
    path, digest = pdf

    def handler(request):
        assert request.method == "GET"
        if request.url.path.endswith("/missing"):
            return httpx.Response(404)
        return httpx.Response(200, json={"items": [paper("live", digest)]})

    client = make_client(handler, verified=IMPORT_VERIFIED, write_collections=["library"])
    client._recent_pdf_imports[("library", digest)] = "missing"
    result = client.import_pdf("library", path, authorization=AUTH, dry_run=False)
    assert result["created"] is False
    assert result["item"]["id"] == "live"


def test_import_pdf_cache_is_scoped_to_session(make_client, pdf):
    path, digest = pdf
    client1 = make_client(
        lambda request: httpx.Response(200, json={"items": [paper("first-account", digest)]}),
        verified=IMPORT_VERIFIED,
        write_collections=["library"],
    )
    client1.import_pdf("library", path, authorization=AUTH, dry_run=False)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.path == "/collections/library/items"
        return httpx.Response(200, json={"items": [paper("second-account", digest)]})

    client2 = make_client(handler, verified=IMPORT_VERIFIED, write_collections=["library"])
    # The request-transport fixture uses fake sessions; change only its state namespace.
    client2.session = "another-test-session-fingerprint"
    result = client2.import_pdf("library", path, authorization=AUTH, dry_run=False)
    assert result["item"]["id"] == "second-account"
    assert len(calls) == 1
