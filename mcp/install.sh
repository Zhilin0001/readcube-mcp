#!/bin/sh
set -eu
bundle_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$bundle_root"
python3 -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ is required"'
if [ ! -x "$bundle_root/.venv/bin/python" ]; then
  python3 -m venv "$bundle_root/.venv"
fi
set -- "$bundle_root"/readcube_agent_client-*.whl
if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
  echo 'Expected exactly one SDK wheel in the bundle.' >&2
  exit 1
fi
"$bundle_root/.venv/bin/python" -m pip install "$1[mcp,realtime]"
"$bundle_root/.venv/bin/python" "$bundle_root/configure.py"
echo 'Installation complete. Import mcp.local.json into a local stdio MCP client.'
