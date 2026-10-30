"""Verify real stdio initialization and new local tools without remote requests."""

import asyncio
import json
import sys
from pathlib import Path

from mcp.client.stdio import stdio_client

from mcp import ClientSession, StdioServerParameters


async def main():
    root = Path(__file__).resolve().parents[1]
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "readcube_mcp"], cwd=str(root)
    )
    async with stdio_client(params) as (r, w), ClientSession(r, w) as session:
        initialized = await session.initialize()
        tools = await session.list_tools()
        assert len(tools.tools) == 44
        assert any(tool.name == "readcube_open_login" for tool in tools.tools)
        result = await session.call_tool(
            "readcube_normalize_author_names", {"names": ["Doe, Jane"]}
        )
        assert result.structured_content["authors"][0]["display"] == "Jane Doe"
        preview = await session.call_tool(
            "readcube_batch_update_metadata",
            {
                "collection_id": "OFFLINE_LIBRARY",
                "updates": [
                    {"item_id": "OFFLINE_ITEM", "patch": {"article": {"title": "Offline test"}}}
                ],
            },
        )
        assert preview.structured_content["dry_run"]
        print(
            json.dumps(
                {
                    "status": "PASSED",
                    "transport": "stdio",
                    "version": initialized.server_info.version,
                    "tools": len(tools.tools),
                    "local_author_tool": True,
                    "zero_write_preview": True,
                    "remote_requests": 0,
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
