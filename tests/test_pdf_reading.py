import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from readcube_client.artifacts import resolve_artifact
from readcube_client.errors import ProtocolError, UnverifiedEndpointError
from readcube_client.pdf import download_pdf, index_fulltext, read_pdf, search_fulltext
from readcube_mcp.server import create_server
from scripts.verify_api import make_test_pdf


@pytest.fixture
def pdf_client(make_client, tmp_path):
    path = tmp_path / "source.pdf"
    make_test_pdf(path)
    content = path.read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    calls = []
    rows = [
        {
            "id": "paper",
            "article": {"title": "Synthetic"},
            "files": [{"name": "original.pdf", "sha256": sha, "file_type": "pdf"}],
        }
    ]

    def handler(request):
        calls.append(request)
        if request.url.host == "s3.amazonaws.com":
            assert "cookie" not in request.headers and "authorization" not in request.headers
            return httpx.Response(200, content=content)
        if request.url.path.endswith("/files_with_urls"):
            assert request.url.params.get_list("item_ids[]") == ["paper"]
            return httpx.Response(
                200,
                json={
                    "paper": [
                        {
                            "sha256": sha,
                            "download_url": "https://s3.amazonaws.com/original?secret=hidden",
                        }
                    ]
                },
            )
        if request.url.path.endswith("/items/paper"):
            return httpx.Response(200, json={"item": rows[0]})
        if request.url.path.endswith("/items"):
            return httpx.Response(200, json={"items": rows, "total": len(rows)})
        pytest.fail(str(request.url))

    client = make_client(handler, verified=("get_item", "files_with_urls", "list_items"))
    return client, rows, calls, content, sha


def test_original_download_text_cache_and_pagination(pdf_client):
    client, _, calls, content, sha = pdf_client
    first = download_pdf(client, "lib", "paper")
    assert Path(first["artifact"]["local_path"]).read_bytes() == content
    assert first["sha256"] == sha and not first["cached"]
    assert download_pdf(client, "lib", "paper")["cached"]
    first_text = read_pdf(client, "lib", "paper", max_chars=100)
    assert "synthetic upload test" in first_text["text"]
    assert not first_text["text_cached"] and first_text["page_count"] == 1
    assert read_pdf(client, "lib", "paper")["text_cached"]
    assert sum(r.url.host == "s3.amazonaws.com" for r in calls) == 1
    assert sum(r.url.path.endswith("/files_with_urls") for r in calls) == 1
    with pytest.raises(ValueError):
        read_pdf(client, "lib", "paper", start_page=2)
    with pytest.raises(ValueError):
        download_pdf(client, "lib", "paper", sha256="a" * 64)


def test_hash_mismatch_and_host_redirects_never_return_invalid_files(pdf_client, monkeypatch):
    client, rows, _, _, sha = pdf_client
    rows[0]["files"][0]["sha256"] = "f" * 64
    with pytest.raises(ProtocolError, match="No authorized"):
        download_pdf(client, "lib", "paper")
    from readcube_client.pdf import _download

    for url in [
        "http://s3.amazonaws.com/file",
        "https://127.0.0.1/file",
        "https://s3.amazonaws.com.evil.test/file",
        "https://user:password@s3.amazonaws.com/file",
    ]:
        with pytest.raises(ProtocolError):
            _download(client, url, client.settings.state_dir / "bad.pdf", sha)


def test_fulltext_index_search_cache_and_deleted_record_filtering(pdf_client):
    client, rows, calls, _, _ = pdf_client
    result = index_fulltext(client, "lib")
    assert result["results"][0]["status"] == "indexed"
    found = search_fulltext(client, "lib", "synthetic upload")
    assert found["items"][0]["page"] == 1 and found["items"][0]["item_id"] == "paper"
    before = len(calls)
    assert not index_fulltext(client, "lib")["results"]
    assert len(calls) == before
    rows.clear()
    assert search_fulltext(client, "lib", "synthetic", refresh=True)["items"] == []


def test_unverified_url_endpoint_does_not_send_download(pdf_client):
    client, _, calls, _, _ = pdf_client
    client.registry.records.pop("files_with_urls")
    with pytest.raises(UnverifiedEndpointError):
        download_pdf(client, "lib", "paper")
    assert all(r.url.path.endswith("/items/paper") for r in calls)


def test_mcp_file_resource_has_exact_original_bytes_and_expiry(pdf_client, monkeypatch):
    client, _, _, content, _ = pdf_client
    server = create_server(lambda: client)

    async def run():
        result = await server.call_tool(
            "readcube_prepare_pdf_attachment", {"collection_id": "lib", "item_id": "paper"}
        )
        assert result.structured_content["chatgpt_upload_confirmed"] is False
        links = [x for x in result.content if x.type == "resource_link"]
        assert len(links) == 1
        artifact = result.structured_content["artifact"]
        path, record = resolve_artifact(client, artifact["id"])
        assert path.read_bytes() == content
        resources = await server.read_resource(links[0].uri)
        assert resources[0].content == content
        manifest = path.parent.parent / "links" / (artifact["id"] + ".json")
        record["expires_at"] = 0
        manifest.write_text(json.dumps(record))
        with pytest.raises(ValueError, match="expired"):
            resolve_artifact(client, artifact["id"])

    asyncio.run(run())


def test_all_supplements_incremental_limits_and_chinese_substrings(pdf_client, monkeypatch):
    client, rows, _, _, sha = pdf_client
    other = "b" * 64
    rows[0]["files"].append({"name": "supplement.pdf", "sha256": other, "file_type": "pdf"})
    from readcube_client import pdf

    monkeypatch.setattr(
        pdf,
        "extract_pdf",
        lambda c, lib, iid, sha256: {
            "document": {
                "pages": [
                    "Main article only" if sha256 == sha else "这里研究光生物调节机制和脑网络变化"
                ],
                "page_count": 1,
                "truncated": False,
                "ocr_required": False,
            }
        },
    )
    first = index_fulltext(client, "lib", limit=1)
    assert not first["complete"] and first["remaining_attachments"] == [
        {"item_id": "paper", "sha256": other}
    ]
    second = index_fulltext(client, "lib", limit=1)
    assert second["complete"] and second["results"][0]["sha256"] == other
    hits = search_fulltext(client, "lib", "光生物调节")
    assert hits["indexed_documents"] == 2 and hits["items"][0]["sha256"] == other


def test_binary_corruption_is_rejected_without_partial_output(pdf_client):
    client, _, _, content, sha = pdf_client
    from readcube_client.pdf import _download

    client.http._transport = httpx.MockTransport(
        lambda r: httpx.Response(200, content=content + b"corrupt")
    )
    target = client.settings.state_dir / "bad.pdf"
    with pytest.raises(ProtocolError, match="SHA-256"):
        _download(client, "https://s3.amazonaws.com/paper", target, sha)
    assert not target.exists() and not list(target.parent.glob(".part-*"))


def test_storage_ignores_client_auth_and_automatic_redirects(pdf_client):
    client, _, _, _content, sha = pdf_client
    from readcube_client.pdf import _download

    calls = []

    def redirect(request):
        calls.append(request)
        assert "authorization" not in request.headers and "cookie" not in request.headers
        return httpx.Response(302, headers={"Location": "https://not-allowed.example/private"})

    client.http.auth = httpx.BasicAuth("test-only", "not-a-real-secret")
    client.http.follow_redirects = True
    client.http._transport = httpx.MockTransport(redirect)
    with pytest.raises(ProtocolError, match="not allowed"):
        _download(
            client, "https://s3.amazonaws.com/paper", client.settings.state_dir / "blocked.pdf", sha
        )
    assert len(calls) == 1


def test_concurrent_downloads_share_one_original_transfer(pdf_client):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    client, _, calls, _, _ = pdf_client
    barrier = threading.Barrier(2)

    def run(_):
        barrier.wait(timeout=3)
        return download_pdf(client, "lib", "paper")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert {r["cached"] for r in results} == {False, True}
    assert sum(r.url.host == "s3.amazonaws.com" for r in calls) == 1


def test_original_storage_get_retries_transient_connection_failure(pdf_client):
    client, _, _, content, sha = pdf_client
    from readcube_client.pdf import _download

    client.settings.retries = 1
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("Synthetic transient failure")
        return httpx.Response(200, content=content)

    client.http._transport = httpx.MockTransport(handler)
    target = client.settings.state_dir / "recovered.pdf"
    _download(client, "https://s3.amazonaws.com/paper", target, sha)
    assert len(calls) == 2 and target.read_bytes() == content
    assert not list(target.parent.glob(".part-*"))
