"""Generate local stdio configuration without copying credentials."""

import json
import os
from pathlib import Path

root = Path(__file__).resolve().parent
settings = root / "readcube.local.toml"
if not settings.exists():
    settings.write_text((root / "readcube.example.toml").read_text())
    os.chmod(settings, 0o600)
configuration = {"mcpServers": {"readcube": {"command": str(root / "start.sh"), "args": []}}}
path = root / "mcp.local.json"
path.write_text(json.dumps(configuration, ensure_ascii=False, indent=2) + "\n")
os.chmod(path, 0o600)
print("Generated mcp.local.json; existing session files and write scopes were not changed.")
