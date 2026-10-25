"""Build a portable MCP bundle plus a separate ready-to-use config for this workspace."""

import asyncio
import hashlib
import json
import os
import shlex
import shutil
import sys
import tomllib
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from readcube_mcp.server import create_server

ROOT = Path(__file__).resolve().parents[1]


async def main():
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    folder = ROOT / "dist" / f"readcube-mcp-{version}"
    folder.mkdir(parents=True, exist_ok=True)
    wheel = ROOT / "dist" / f"readcube_agent_client-{version}-py3-none-any.whl"
    if not wheel.exists():
        raise SystemExit("Build the current SDK wheel first: python -m build")
    mappings = [
        (ROOT / "mcp" / name, name)
        for name in ["README.md", "start.sh", "install.sh", "configure.py"]
    ]
    mappings += [(wheel, wheel.name), (ROOT / "readcube.example.toml", "readcube.example.toml")]
    mappings += [
        (ROOT / "scripts" / name, "scripts/" + name)
        for name in ["login_local.py", "smoke_mcp.py", "verify_api.py", "benchmark_mcp.py"]
    ]
    mappings += [
        (ROOT / "docs" / name, "docs/" + name)
        for name in [
            "readcube-api.md",
            "reverse-engineering-report.md",
            "verification-results.json",
            "performance.md",
        ]
    ]
    portable = []
    for source, name in mappings:
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o755 if target.suffix == ".sh" else 0o644)
        portable.append(name)
    tools = await create_server().list_tools()
    manifest = {
        "name": "ReadCube Papers",
        "version": version,
        "transport": "stdio",
        "tool_count": len(tools),
        "tools": [t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in tools],
    }
    (folder / "tools.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    portable.append("tools.json")
    archive = ROOT / "dist" / f"readcube-mcp-{version}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for name in portable:
            zip_file.write(folder / name, arcname=f"readcube-mcp-{version}/{name}")
    # Machine-specific launch/config are deliberately created after the zip file.
    # No cwd support is required from the consuming MCP client.
    launcher = folder / "start.local.sh"
    launcher.write_text(
        "#!/bin/sh\nset -eu\ncd "
        + shlex.quote(str(ROOT))
        + "\nexec "
        + shlex.quote(str(ROOT / ".venv/bin/python"))
        + " -m readcube_mcp --config "
        + shlex.quote(str(ROOT / "readcube.local.toml"))
        + "\n"
    )
    launcher.chmod(0o700)
    configuration = {"mcpServers": {"readcube": {"command": str(launcher), "args": []}}}
    config_path = folder / "mcp.local.json"
    config_path.write_text(json.dumps(configuration, ensure_ascii=False, indent=2) + "\n")
    os.chmod(config_path, 0o600)
    (ROOT / "examples/mcp.local.json").write_text(
        json.dumps(configuration, ensure_ascii=False, indent=2) + "\n"
    )
    os.chmod(ROOT / "examples/mcp.local.json", 0o600)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (archive.with_suffix(".zip.sha256")).write_text(f"{digest}  {archive.name}\n")
    print(
        json.dumps(
            {
                "version": version,
                "tools": len(tools),
                "bundle": str(archive),
                "local_config": str(config_path),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
