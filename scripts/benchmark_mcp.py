"""Measure real MCP handlers with redacted timing output; reads/dry-runs by default.

Optional note writes must be explicitly enabled for an authorized synthetic test
Collection. Original notes are restored only after verifying no intervening edit.
"""

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from readcube_client import ReadCubeClient
from readcube_client.auth import private_json_write
from readcube_mcp.runtime import ReadCubeClientPool
from readcube_mcp.server import create_server


async def benchmark(args):
    requests = []

    def factory(settings):
        client = ReadCubeClient(settings)
        request = client.http.request

        def timed(*a, **kw):
            start = time.perf_counter()
            try:
                return request(*a, **kw)
            finally:
                requests.append(time.perf_counter() - start)

        client.http.request = timed
        return client

    measurements = []
    with ReadCubeClientPool(args.config, client_factory=factory) as pool:
        server = create_server(pool)

        async def measure(label, tool, arguments):
            before = len(requests)
            start = time.perf_counter()
            result = await server.call_tool(tool, arguments)
            if result.is_error:
                raise RuntimeError(f"{label}: MCP tool failed")
            data = result.structured_content
            row = {
                "label": label,
                "seconds": round(time.perf_counter() - start, 4),
                "requests": len(requests) - before,
                "response_bytes": len(json.dumps(data).encode()),
                "source": data.get("source"),
            }
            measurements.append(row)
            print(json.dumps(row), flush=True)
            return data

        await measure("capabilities", "readcube_capabilities", {})
        cid = {"collection_id": args.collection}
        count = await measure("count_live", "readcube_count_papers", cid)
        cold = await measure(
            "query_cold", "readcube_query_library", cid | {"refresh": True, "limit": 5}
        )
        if count["total"] != cold["total"]:
            raise RuntimeError("Library changed between count and full-scan checks")
        for i in range(3):
            await measure(f"query_warm_{i + 1}", "readcube_query_library", cid | {"limit": 5})
        for i in range(2):
            await measure(
                f"legacy_search_{i + 1}", "readcube_search_papers", cid | {"query": args.query}
            )
        for i in range(2):
            await measure(
                f"compact_search_{i + 1}",
                "readcube_query_library",
                cid | {"query": args.query, "limit": 5},
            )

        restored = None
        if args.note_collection and args.note_item:
            note_ids = {"collection_id": args.note_collection, "item_id": args.note_item}
            marker = "Codex isolated performance check " + str(uuid.uuid4())
            for i in range(3):
                await measure(
                    f"note_preview_{i + 1}",
                    "readcube_append_note",
                    note_ids | {"text": marker, "dry_run": True},
                )
            if args.execute_notes:
                collections = await server.call_tool("readcube_list_collections", {})
                collection = next(
                    c
                    for c in collections.structured_content["result"]
                    if c["id"] == args.note_collection
                )
                if not (collection.get("name") or "").startswith("Codex API Test "):
                    raise ValueError(
                        "Live note benchmark is restricted to a synthetic test Collection"
                    )
                original = (
                    await server.call_tool("readcube_get_paper", note_ids)
                ).structured_content
                notes = (original.get("user_data") or {}).get("notes") or ""
                expected = notes + ("\n" if notes and not notes.endswith("\n") else "") + marker
                backup = args.output.with_suffix(".note-backup.json")
                private_json_write(backup, note_ids | {"notes": notes, "expected": expected})
                await measure(
                    "test_library_warmup",
                    "readcube_query_library",
                    {"collection_id": args.note_collection, "refresh": True, "limit": 1},
                )
                try:
                    executed = await measure(
                        "note_append_verified",
                        "readcube_append_note",
                        note_ids | {"text": marker, "authorized": True, "dry_run": False},
                    )
                    assert executed["verified"] and executed["changed"]
                    again = await measure(
                        "note_append_idempotent",
                        "readcube_append_note",
                        note_ids | {"text": marker, "authorized": True, "dry_run": False},
                    )
                    assert not again["changed"]
                    found = await measure(
                        "query_after_note",
                        "readcube_query_library",
                        {
                            "collection_id": args.note_collection,
                            "query": marker,
                            "field": "notes",
                            "limit": 1,
                        },
                    )
                    assert found["source"] == "cache" and found["matched"] == 1
                finally:
                    current = (
                        await server.call_tool("readcube_get_paper", note_ids)
                    ).structured_content
                    current_notes = (current.get("user_data") or {}).get("notes") or ""
                    if current_notes == expected:
                        await server.call_tool("readcube_update_notes", note_ids | {"notes": notes})
                        await server.call_tool(
                            "readcube_update_notes",
                            note_ids | {"notes": notes, "authorized": True, "dry_run": False},
                        )
                        check = (
                            await server.call_tool("readcube_get_paper", note_ids)
                        ).structured_content
                        restored = (check.get("user_data") or {}).get("notes") or ""
                        if restored != notes:
                            raise RuntimeError("Original note restoration could not be verified")
                        restored = True
                    elif current_notes == notes:
                        restored = True
                    else:
                        raise RuntimeError(
                            "Concurrent note edit detected; inspect private backup before retrying"
                        )
        report = {
            "measurements": measurements,
            "total": count["total"],
            "note_restored": restored,
            "transport": "in_process_mcp_handlers",
        }
        private_json_write(args.output, report)
        print(
            json.dumps(
                {"report": str(args.output), "total": count["total"], "note_restored": restored}
            ),
            flush=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="readcube.local.toml")
    parser.add_argument("--collection", required=True)
    parser.add_argument("--query", default="photobiomodulation")
    parser.add_argument("--note-collection")
    parser.add_argument("--note-item")
    parser.add_argument("--execute-notes", action="store_true")
    parser.add_argument("--output", type=Path, default=Path(".state/performance/optimized.json"))
    options = parser.parse_args()
    if bool(options.note_collection) != bool(options.note_item):
        parser.error("--note-collection and --note-item must be provided together")
    if options.execute_notes and not options.note_item:
        parser.error("--execute-notes requires test note identifiers")
    asyncio.run(benchmark(options))
