import hashlib
import json
from pathlib import Path

import httpx
import pytest

from readcube_client import WriteAuthorization
from readcube_client.errors import (
    AuthorizationError,
    ProtocolError,
    TransportError,
    UnverifiedEndpointError,
    UploadPendingError,
)
from readcube_client.evidence import _PDF_SCOPES, _UPLOAD_CONTRACTS


def test_project_contract_pins_match_recorded_semantic_evidence(make_client):
    client = make_client(lambda request: pytest.fail("No request expected"))
    recorded = json.loads(Path("docs/verification-results.json").read_text())["operations"]
    for name, expected in _UPLOAD_CONTRACTS.items():
        assert recorded[name]["verification"] == "VERIFIED"
        assert recorded[name]["semantic_check"] is True
        assert recorded[name]["contract_sha256"] == client.registry.signature(name) == expected
    caps = client.capabilities()
    assert caps["upload_pdf_flow"]["verification"] == "PROJECT_VERIFIED_FOR_PDF"
    assert caps["upload_pdf_flow"]["session_verification"] == "UNVERIFIED"
    assert not client.registry.verified("upload_pdf_flow")
    with pytest.raises(UnverifiedEndpointError):
        client.get_item("lib", "paper")


def test_project_verified_upload_fresh_session_checks_hash_and_sends_no_cookies(
    make_client, tmp_path, monkeypatch
):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(b"%PDF-1.4\nsynthetic\n%%EOF")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    calls, storage_calls = [], []

    def main(request):
        calls.append(request.method)
        if request.url.path.endswith("add_file"):
            if calls.count("POST") == 1:
                return httpx.Response(
                    200,
                    json={
                        "upload_id": "u1",
                        "upload_url": "https://s3.amazonaws.com/bucket/fake?token=never-log",
                    },
                )
            return httpx.Response(200, json={"item": {"id": "paper"}})
        if request.url.path.endswith("uploads_pending"):
            return httpx.Response(200, json={"u1": {"status": "completed", "hash": digest}})
        return httpx.Response(200, json={"item": {"id": "paper", "files": [{"sha256": digest}]}})

    client = make_client(main, write_collections=["lib"], upload_hosts=["s3.amazonaws.com"])
    original = httpx.Client

    def storage(request):
        storage_calls.append(request)
        return httpx.Response(200)

    monkeypatch.setattr(
        "readcube_client.client.httpx.Client",
        lambda **kwargs: original(transport=httpx.MockTransport(storage), **kwargs),
    )
    result = client.upload_pdf(
        "lib",
        "paper",
        path,
        authorization=WriteAuthorization(collection_id="lib", authorized=True),
        dry_run=False,
    )
    assert result["associated"] and result["sha256"] == digest
    assert calls == ["POST", "GET", "POST", "GET"]
    assert len(storage_calls) == 1 and "cookie" not in storage_calls[0].headers
    assert not client.registry.verified("add_file")
    with pytest.raises(UnverifiedEndpointError):
        client.get_item("lib", "paper")


def test_changed_pdf_contract_or_missing_authorization_fails_before_write(make_client, tmp_path):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(b"%PDF-1.4\nsynthetic")
    sent = []
    client = make_client(lambda r: sent.append(r), write_collections=["lib"])
    with pytest.raises(AuthorizationError):
        client.upload_pdf("lib", "paper", path, dry_run=False)
    assert not sent
    client.registry.catalog["add_file"]["body_contract"] = "modified"
    assert not client.registry.project_pdf_verified("upload_pdf_flow")
    with pytest.raises(UnverifiedEndpointError):
        client.upload_pdf(
            "lib",
            "paper",
            path,
            authorization=WriteAuthorization(collection_id="lib", authorized=True),
            dry_run=False,
        )
    assert not sent


def test_changed_frontend_version_does_not_inherit_project_evidence(make_client, tmp_path):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(b"%PDF-1.4\nsynthetic")
    client = make_client(
        lambda request: pytest.fail("Must not transmit"),
        write_collections=["lib"],
        client_version="9.9.9",
    )
    assert not client.registry.project_pdf_verified("upload_pdf_flow")
    with pytest.raises(UnverifiedEndpointError):
        client.upload_pdf(
            "lib",
            "paper",
            path,
            authorization=WriteAuthorization(collection_id="lib", authorized=True),
            dry_run=False,
        )


def test_project_upload_hash_mismatch_never_reports_success(make_client, tmp_path):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(b"%PDF-1.4\nsynthetic")
    client = make_client(
        lambda r: httpx.Response(200, json={"item": {"id": "paper", "files": []}}),
        write_collections=["lib"],
    )
    with pytest.raises(ProtocolError, match="not confirmed"):
        client.upload_pdf(
            "lib",
            "paper",
            path,
            authorization=WriteAuthorization(collection_id="lib", authorized=True),
            dry_run=False,
        )


def test_correct_hash_on_wrong_item_is_not_success(make_client, tmp_path):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(b"%PDF-1.4\nsynthetic")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    def main(request):
        if request.method == "POST":
            return httpx.Response(200, json={"item": {"id": "paper"}})
        return httpx.Response(200, json={"item": {"id": "wrong", "files": [{"sha256": digest}]}})

    client = make_client(main, write_collections=["lib"])
    with pytest.raises(ProtocolError, match="different item"):
        client.upload_pdf(
            "lib",
            "paper",
            path,
            authorization=WriteAuthorization(collection_id="lib", authorized=True),
            dry_run=False,
        )


def test_other_session_unverified_operations_stay_blocked(make_client):
    client = make_client(lambda r: pytest.fail("Unexpected request"))
    for flow, operations in _PDF_SCOPES.items():
        with client.registry.pdf_upload_scope(flow):
            with pytest.raises(UnverifiedEndpointError):
                client.registry.require("delete_item")
            assert all(client.registry.allowed_in_current_scope(name) for name in operations)


def test_uncertain_attachment_never_reposts_and_recovers_by_hash(make_client, tmp_path):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(b"%PDF-1.4\nsynthetic")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    calls = []
    available = False

    def main(request):
        calls.append(request.method)
        if request.method == "POST":
            return httpx.Response(200, json={"item": {"id": "paper"}})
        if not available:
            raise httpx.ReadTimeout("synthetic readback failure")
        return httpx.Response(200, json={"item": {"id": "paper", "files": [{"sha256": digest}]}})

    client = make_client(main, write_collections=["lib"])
    auth = WriteAuthorization(collection_id="lib", authorized=True)
    with pytest.raises(TransportError):
        client.upload_pdf("lib", "paper", path, authorization=auth, dry_run=False)
    with pytest.raises(UploadPendingError, match="uncertain"):
        client.upload_pdf("lib", "paper", path, authorization=auth, dry_run=False)
    assert calls.count("POST") == 1
    available = True
    recovered = client.upload_pdf("lib", "paper", path, authorization=auth, dry_run=False)
    assert recovered["reconciled"] and recovered["associated"]
    assert calls.count("POST") == 1
    journal = next((client.settings.state_dir / "pdf-upload-guard").glob("*.json"))
    assert journal.stat().st_mode & 0o777 == 0o600
    assert json.loads(journal.read_text())["state"] == "verified"


def test_uncertain_storage_transfer_stops_repeated_upload(make_client, tmp_path, monkeypatch):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(b"%PDF-1.4\nsynthetic")
    calls = []

    def main(request):
        calls.append(request.method)
        if request.method == "POST":
            return httpx.Response(
                200, json={"upload_id": "u1", "upload_url": "https://s3.amazonaws.com/test"}
            )
        return httpx.Response(200, json={"item": {"id": "paper", "files": []}})

    client = make_client(main, write_collections=["lib"], upload_hosts=["s3.amazonaws.com"])
    original = httpx.Client

    def storage(request):
        raise httpx.ReadTimeout("synthetic uncertain transfer")

    monkeypatch.setattr(
        "readcube_client.client.httpx.Client",
        lambda **kwargs: original(transport=httpx.MockTransport(storage), **kwargs),
    )
    auth = WriteAuthorization(collection_id="lib", authorized=True)
    with pytest.raises(TransportError):
        client.upload_pdf("lib", "paper", path, authorization=auth, dry_run=False)
    with pytest.raises(UploadPendingError):
        client.upload_pdf("lib", "paper", path, authorization=auth, dry_run=False)
    assert calls.count("POST") == 1


def test_pdf_import_project_evidence_without_session_ledger_and_duplicate_guard(
    make_client, tmp_path
):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(b"%PDF-1.4\nsynthetic")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    calls = []

    def main(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/items") and request.method == "GET":
            return httpx.Response(200, json={"items": [], "total": 0})
        if request.method == "POST":
            return httpx.Response(200, json={"item": {"id": "paper"}})
        return httpx.Response(200, json={"item": {"id": "paper", "files": [{"sha256": digest}]}})

    auth = WriteAuthorization(collection_id="lib", authorized=True)
    client1 = make_client(main, write_collections=["lib"])
    result = client1.import_pdf("lib", path, authorization=auth, dry_run=False)
    assert result["created"] and result["associated"]
    client2 = make_client(main, write_collections=["lib"])
    client2.session = "another-session"
    second = client2.import_pdf("lib", path, authorization=auth, dry_run=False)
    assert not second["created"] and second["reconciled"]
    assert sum(method == "POST" for method, _ in calls) == 1


def test_expired_session_and_remote_permission_rejection_fail_closed(make_client, tmp_path):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(b"%PDF-1.4\nsynthetic")
    calls = []
    client = make_client(
        lambda request: calls.append(request.method) or httpx.Response(403),
        write_collections=["lib"],
    )
    from readcube_client.errors import AuthenticationError

    with pytest.raises(AuthenticationError):
        client.upload_pdf(
            "lib",
            "paper",
            path,
            authorization=WriteAuthorization(collection_id="lib", authorized=True),
            dry_run=False,
        )
    assert calls == ["POST"]
    journal = next((client.settings.state_dir / "pdf-upload-guard").glob("*.json"))
    assert json.loads(journal.read_text())["state"] == "rejected"
