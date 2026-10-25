#!/bin/sh
set -eu
bundle_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$bundle_root"
if [ ! -x "$bundle_root/.venv/bin/python" ]; then
  echo 'Run ./install.sh in this bundle first.' >&2
  exit 1
fi
if [ ! -f "$bundle_root/readcube.local.toml" ]; then
  echo 'Missing readcube.local.toml; run ./install.sh to generate a safe initial configuration.' >&2
  exit 1
fi
exec "$bundle_root/.venv/bin/python" -m readcube_mcp --config "$bundle_root/readcube.local.toml"
