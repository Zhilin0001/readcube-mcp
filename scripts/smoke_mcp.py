"""Initialize the real stdio server and call verified read tools, without printing library data."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from mcp.client.stdio import stdio_client

from mcp import ClientSession, StdioServerParameters


async def check(config: str | None, connection_config: str | None = None):
    root = Path(__file__).resolve().parents[1]
    args = ["-m", "readcube_mcp"]
    if config:
        args += ["--config", str(Path(config).resolve())]
    params = StdioServerParameters(command=sys.executable, args=args, cwd=root)
    if connection_config:
        spec = json.loads(Path(connection_config).read_text())["mcpServers"]["readcube"]
        params = StdioServerParameters(
            command=spec["command"],
            args=spec.get("args", []),
            cwd=spec.get("cwd"),
            env=spec.get("env"),
        )
    async with (
        stdio_client(params) as (reader, writer),
        ClientSession(reader, writer, read_timeout_seconds=45) as session,
    ):
        initialized = await session.initialize()
        tools = await session.list_tools()
        capabilities = await session.call_tool("readcube_capabilities", {})
        if capabilities.is_error or capabilities.structured_content is None:
            raise RuntimeError("MCP capabilities did not return structured JSON")
        collections = await session.call_tool("readcube_list_collections", {})
        if collections.is_error or collections.structured_content is None:
            raise RuntimeError("MCP authenticated read failed")
        dry_run = await session.call_tool(
            "readcube_update_notes",
            {
                "collection_id": "MCP_DRY_RUN_COLLECTION",
                "item_id": "MCP_DRY_RUN_ITEM",
                "notes": "Connection validation only",
                "dry_run": True,
            },
        )
        if (
            dry_run.is_error
            or not dry_run.structured_content
            or dry_run.structured_content.get("dry_run") is not True
        ):
            raise RuntimeError("MCP dry-run did not return a zero-write plan")
        print(
            json.dumps(
                {
                    "status": "PASSED",
                    "transport": "stdio",
                    "tools": len(tools.tools),
                    "server_version": initialized.server_info.version,
                    "structured_capabilities": True,
                    "authenticated_collection_read": True,
                    "zero_write_plan": True,
                }
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument(
        "--connection-config", help="Read the exact generated mcpServers.readcube entry"
    )
    args = parser.parse_args()
    asyncio.run(check(args.config, args.connection_config))
