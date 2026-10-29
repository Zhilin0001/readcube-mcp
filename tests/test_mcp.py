import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from readcube_client import ReadCubeClient
from readcube_mcp.server import create_server


def test_mcp_contract_and_unverified_dryrun(make_client):
    client = make_client(lambda request: (_ for _ in ()).throw(AssertionError("No network")))
    server = create_server(lambda: client)

    async def check():
        tools = await server.list_tools()
        by_name = {tool.name: tool for tool in tools}
        assert "readcube_search_papers" in by_name
        assert "readcube_upload_pdf" in by_name
        assert len(tools) == 42
        assert by_name["readcube_count_papers"].annotations.read_only_hint is True
        assert all(tool.output_schema for tool in tools)
        assert by_name["readcube_delete_paper"].annotations.destructive_hint is True
        for name in ("readcube_delete_annotation", "readcube_delete_smartlist"):
            assert by_name[name].annotations.destructive_hint is True
            assert by_name[name].input_schema["properties"]["confirmation"]["default"] == ""
        for name in (
            "readcube_import_pdf",
            "readcube_create_annotation",
            "readcube_update_annotation",
            "readcube_create_smartlist",
            "readcube_update_smartlist",
        ):
            properties = by_name[name].input_schema["properties"]
            assert properties["dry_run"]["default"] is True
            assert properties["authorized"]["default"] is False
        duration = by_name["readcube_watch_library"].input_schema["properties"]["duration"]
        assert duration["maximum"] == 30
        assert duration["exclusiveMinimum"] == 0
        schema = by_name["readcube_update_notes"].input_schema
        assert schema["properties"]["dry_run"]["default"] is True
        assert schema["properties"]["authorized"]["default"] is False
        result = await server.call_tool(
            "readcube_update_notes",
            {"collection_id": "library", "item_id": "paper", "notes": "test"},
        )
        assert not result.is_error
        assert result.structured_content["dry_run"] is True
        assert result.structured_content["verified"] is False

    asyncio.run(check())


def test_annotation_validation_returns_safe_errors_and_single_write_plan(make_client):
    client = make_client(lambda request: (_ for _ in ()).throw(AssertionError("No network")))
    server = create_server(lambda: client)

    async def check():
        args = {
            "collection_id": "library",
            "item_id": "paper",
            "annotation": {
                "type": "note",
                "sha256": "a" * 64,
                "page_start": 0,
                "position": [72, 720],
                "note": "synthetic note",
            },
        }
        result = await server.call_tool("readcube_create_annotation", args)
        data = result.structured_content
        assert data["dry_run"] is True
        assert len(data["body"]["data"]) == 1
        assert data["body"]["data"][0]["id"] == "paper"
        for name, invalid_args in (
            ("readcube_create_annotation", args | {"annotation": {"type": "secret-input-marker"}}),
            (
                "readcube_update_annotation",
                {
                    "collection_id": "library",
                    "item_id": "paper",
                    "annotation_id": "annot",
                    "patch": {"unknown": "secret-input-marker"},
                },
            ),
        ):
            with pytest.raises(ToolError) as caught:
                await server.call_tool(name, invalid_args)
            assert "secret-input-marker" not in str(caught.value)
            assert "Invalid annotation" in str(caught.value)

    asyncio.run(check())


def test_extended_deletes_require_exact_confirmation(make_client):
    client = make_client(
        lambda request: (_ for _ in ()).throw(AssertionError("No network")),
        write_collections=["library"],
    )
    server = create_server(lambda: client)

    async def check():
        shared = {
            "collection_id": "library",
            "authorized": True,
            "dry_run": False,
            "confirmation": "DELETE wrong-id",
        }
        for name, args in (
            ("readcube_delete_annotation", {"item_id": "paper", "annotation_id": "annot"}),
            ("readcube_delete_smartlist", {"smartlist_id": "smart"}),
        ):
            with pytest.raises(ToolError, match="confirmation"):
                await server.call_tool(name, shared | args)

    asyncio.run(check())


def test_pdf_import_needs_configured_file_roots(make_client):
    client = make_client(lambda request: (_ for _ in ()).throw(AssertionError("No network")))
    server = create_server(lambda: client)

    async def check():
        with pytest.raises(ToolError, match="UPLOAD_ROOTS"):
            await server.call_tool(
                "readcube_import_pdf", {"collection_id": "library", "path": "/not-read.pdf"}
            )

    asyncio.run(check())


def test_watch_duration_is_bounded_before_client_runs(make_client, monkeypatch):
    client = make_client(lambda request: (_ for _ in ()).throw(AssertionError("No network")))
    calls = []

    def watch(collection_id, *, duration):
        calls.append((collection_id, duration))
        return {"mode": "event_notifications_with_full_scan_reconciliation", "added": []}

    monkeypatch.setattr(client, "watch_changes", watch, raising=False)
    server = create_server(lambda: client)

    async def check():
        for duration in (0, 31):
            with pytest.raises(ToolError):
                await server.call_tool(
                    "readcube_watch_library", {"collection_id": "library", "duration": duration}
                )
        assert calls == []
        result = await server.call_tool("readcube_watch_library", {"collection_id": "library"})
        assert calls == [("library", 5.0)]
        assert result.structured_content["added"] == []

    asyncio.run(check())


def test_mcp_production_rejects_unverified_read(make_client):
    client = make_client(lambda request: (_ for _ in ()).throw(AssertionError("No network")))
    assert isinstance(client, ReadCubeClient) and not client._research
    server = create_server(lambda: client)

    async def check():
        with pytest.raises(ToolError, match="UNVERIFIED"):
            await server.call_tool("readcube_list_collections", {})

    asyncio.run(check())
