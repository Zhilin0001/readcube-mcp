# ReadCube MCP 0.2.0

A Python 3.11+ local stdio MCP server with **27 tools**, built on the ReadCube SDK. Distribution bundles contain no passwords, cookies, session-bound verification ledger, or private library content.

## Install from the repository

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[mcp,realtime]'
cp readcube.example.toml readcube.local.toml
.venv/bin/python -m readcube_mcp --config readcube.local.toml
```

Authenticate and verify the required operations before using production tools; see the [main README](https://github.com/Zhilin0001/readcube-mcp#authentication-and-verification). The initial configuration has no authorized write Collections. The source checkout and the portable bundle use different launch layouts; `install.sh` below is intended for an extracted bundle containing its wheel.

## Build and install a portable bundle

From the repository root, with the `dev` dependencies installed:

```bash
.venv/bin/python -m build
.venv/bin/python scripts/build_mcp_bundle.py
```

Extract `dist/readcube-mcp-0.2.0.zip`, enter the extracted directory, and run:

```bash
./install.sh
```

The installer creates a private `.venv`, installs the bundled wheel with MCP and realtime dependencies, and generates `mcp.local.json`. Internet access is required to download dependencies. Existing `readcube.local.toml` is preserved; a newly generated file has an empty write allowlist. Installation does not log in or modify the remote library.

For a client that accepts `mcpServers` JSON, merge the generated `mcpServers.readcube` entry into its existing configuration. The entry invokes `start.sh`, which resolves the bundle directory itself. The client starts the stdio process on demand; a manually started process waiting for input is normal. Keep protocol stdout free of extra output.

The build also creates a separate `start.local.sh` and `mcp.local.json` for the original source workspace. These reuse that workspace's Python environment, configuration, session, and verification ledger. They are excluded from the ZIP. Moving the workspace requires regenerating this machine-specific configuration.

## Authentication and verification

Default local files:

- Session: `~/.config/readcube-client/session.json`, permissions `0600`.
- Verification ledger: `~/.config/readcube-client/verified.json`.

Do not distribute either file. A new installation or changed session is not unlocked by this repository's public verification snapshot. Use the local interactive login helper and perform authorized semantic verification for the relevant operations. `scripts/verify_api.py` defaults to a Collection-list read and a saved dry-run plan; broader live verification needs a dedicated test library. Extended research scripts depend on private test-resource files and are not a general one-command initialization flow. Special SSO/MFA/CSRF flows remain incompletely tested.

## Tool access

The generated `tools.json` contains all 27 tool definitions and JSON schemas. Tools cover library reading and search, identifiers, PDFs, notes/tags, Lists/Smart Lists, annotations, metadata/revisions, and notification-assisted full scans. The SDK's 38 cataloged operations are not 38 separate MCP tools.

Writes default to dry-run. Execution requires human authorization and a matching `write_collections` allowlist. Deletion additionally requires the exact confirmation `DELETE <resource_id>`. PDF tools require an authorized local `upload_roots` directory and an upload-host allowlist. Generating or installing MCP configuration does not expand these permissions.

Annotation creation supports reviewed sticky-note and single-page-highlight shapes; MCP updates are limited to note/has_note/color_id. The watch window is capped at 30 seconds, but complete scans take additional time. Configure client timeouts accordingly. There is no durable server delta cursor.

## Check the connection

With a valid local session and verified `list_collections` operation, run from the extracted bundle:

```bash
.venv/bin/python scripts/smoke_mcp.py --connection-config mcp.local.json
```

This starts a real subprocess, initializes the protocol, lists tools, reads capabilities and Collections, and checks a zero-write dry-run. Errors produce a nonzero exit status.

This package exposes **local stdio**, not a public HTTP URL. A client that accepts only remote HTTP MCP endpoints requires a separate deployment or supported bridge. GitHub hosting alone does not provide a running MCP service or transfer authentication to a cloud environment.
