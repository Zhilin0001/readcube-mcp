# ReadCube MCP

An unofficial Python 3.11+ SDK and local stdio MCP server for managing your own ReadCube Papers library.

**v0.3.3 · 42 local MCP tools · 40 cataloged API operations and workflows, gated by per-session verification.** Supports reference search and import, PDFs, notes, tags, Lists, Smart Lists, annotations, and notification-assisted synchronization.

Verification was performed on October 24–25, 2026, using an explicitly authorized private test Collection. The published results cover the documented requests and test cases, not every account role, parameter, or authentication flow. This project is not affiliated with ReadCube.

## Local macOS login in v0.3.3

Say “Open the ReadCube login window” to call `readcube_open_login` from the local stdio server. By default, macOS Terminal opens the login helper; `mode="dialog"` instead opens email and masked-password dialogs. Credentials go directly to the local helper, not tool arguments or chat. The MCP response confirms only that the helper was started; the window reports whether sign-in and a read-only connection check succeeded. Failed or cancelled login leaves the old session in place. The saved session is scoped to this Mac, and a changed session requires its own endpoint verification. SSO/MFA is not implemented. The remote HTTP service does not expose this local-only tool.

## Pagination recovery in v0.3.2

When a page total changes, a cursor is missing or pages repeat records, complete scans restart from page one up to `pagination_retries` times (default 2). Only a fully validated attempt is returned; failed scans never feed import deduplication. If every attempt fails, the operation reports the cause and attempts and performs no import. Repeated scans can take longer, and stable page counts do not provide a transactional snapshot against concurrent external changes.

## New in v0.3.1

Live testing also fixed transient storage-download failures, metadata readback of server-managed audit timestamps, and batch locking that could block ordinary cached queries.

- Original PDF downloads with exact SHA-256 verification and private byte/text caches.
- PDF text reading with page bounds and continuation offsets. Image-only scans are flagged for OCR.
- Cached author search, per-name statistics and exact-DOI deduplication without deleting references.
- Batch CSV, RIS and BibTeX exports as file resources.
- Authorized batch metadata patches with private originals, per-item read-back and partial-failure reports.
- Incremental full-text indexing across article/supplement PDFs, English/Chinese search and page snippets.
- Expiring file-resource delivery to compatible hosts; optional HTTPS download capabilities for cloud use. Compatible ChatGPT clients get a user-clicked native upload button, with a download fallback; actual host integration remains to be tested online.
- Conservative author-name formatting without expanding initials or merging people.

See [examples, verification command, performance boundaries and file-delivery limitations](docs/library-tools.md). The new PDF URL request is SOURCE_CONFIRMED but remains UNVERIFIED until `scripts/verify_pdf.py` succeeds in the operator's own session. Mock tests do not unlock production endpoints.

## Features

- List Collections, Lists, and references with complete scroll pagination.
- Search by exact DOI or PMID, or a case-insensitive title substring.
- Import DOI/PMID records and create or update reference metadata through the SDK.
- Attach a PDF to an existing reference or import a PDF as a new reference.
- Add a supplemental PDF and explicitly select the primary file through the SDK.
- Manage notes, tags, List membership, and saved-query Smart Lists.
- Read annotations; create sticky notes and single-page highlights; update note text/color and delete individually confirmed annotations.
- Detect changes through complete scans, optionally triggered by Bayeux notifications.
- Return structured JSON to agents, with dry-run plans, write allowlists, and separate deletion confirmation.

The SDK catalog contains 40 operations/workflows; the MCP server groups its supported functionality into 42 local tools, including local cached workflows and the macOS login launcher. SDK-only methods, such as primary-file selection, are not automatically exposed as MCP tools.

## List organization in v0.2.2

`readcube_move_list(collection_id, list_id, parent_id)` moves an existing List within its library; `parent_id=null` moves it to the root. It preserves the name and reference memberships, rejects self/descendant cycles and missing or foreign-library parents, and verifies the saved parent with an independent read. Dry-run, explicit authorization and the Collection allowlist still apply. A new process is needed to load the additional tool. The new operation remains UNVERIFIED on other installations until separately checked in their session-scoped ledger.

## Fast local library workflows

- `readcube_count_papers(collection_id)` returns the live server-reported total in one small request, without scanning the library.
- `readcube_workflow_status(collection_id)` checks the effective write allowlist and verification locally before a write is attempted.
- `readcube_query_library(collection_id, query="", read_only=True)` returns reading counts and a bounded recent list. It also searches titles, exact DOI/PMID, notes, or tags. The first query performs a complete scan; repeated queries reuse a session-scoped private index for up to 300 seconds. Results include `source`, `as_of`, `age_seconds`, total matches, and truncation status. Use `refresh=True` or `max_age_seconds=0` for a fresh scan. Failed scans never create partial indexes, and refresh errors are surfaced rather than silently returning stale data.
- `readcube_append_note(collection_id, item_id, text)` defaults to a dry-run. Execution requires the concrete human authorization and an allowlisted Collection, reads the current notes, plans the append, writes only if absent, verifies the saved text with a separate read, and refreshes only that cached item while retaining the original full-scan timestamp. Ambiguous writes invalidate the index. It never treats a cached note as the source for a write. The upstream notes API replaces a field without compare-and-swap, so simultaneous edits in other apps remain a concurrency limitation.

The CLI exposes the same workflows immediately, including in a host that has not reloaded its MCP tool list:

```bash
readcube --config readcube.local.toml workflow-status --collection-id COLLECTION_ID
readcube --config readcube.local.toml query-library COLLECTION_ID --query NEST --field notes
readcube --config readcube.local.toml query-library COLLECTION_ID --read-only --limit 10
readcube --config readcube.local.toml append-note COLLECTION_ID ITEM_ID 'Authorized marker'
readcube --config readcube.local.toml --execute --authorize-collection COLLECTION_ID append-note COLLECTION_ID ITEM_ID 'Authorized marker'
```

The server reuses a pool of up to four HTTP clients. Each invocation still reloads configuration, validates local session expiry and permissions, and checks verification evidence; changes retire old clients. Response cookies are reset to the verified saved session on checkout without discarding HTTP connections. Existing processes need one restart to load v0.3.3 and its 42 local tools; subsequent allowlist edits take effect on the next invocation. A ReadCube `unread=false` mark or an annotation is not proof that the entire article has been read. These workflows do not expand allowlists automatically or change deletion confirmation requirements.

See [performance measurements and tradeoffs](docs/performance.md). Concurrent cold queries share a scan; scans do not hold the write lock during network work. A scan overlapping a local write retries once rather than overwriting newer notes. Compact query notes are previews of at most 320 characters; full notes remain searchable and available through `readcube_get_paper`.

## Install from source

```bash
git clone https://github.com/Zhilin0001/readcube-mcp.git
cd readcube-mcp
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[mcp,realtime]'
```

For tests, linting, and packaging, also install the `dev` extra:

```bash
.venv/bin/python -m pip install -e '.[mcp,realtime,cloud,dev]'
```

The development environment used macOS and Python 3.13. Python 3.11+ is declared supported, but a separate 3.11/3.12 test matrix has not been run. The MCP implementation uses the Python SDK **2.x** `MCPServer` API. The development dependency snapshot is in [requirements-lock.txt](requirements-lock.txt).

## Authentication and verification

Run the interactive login helper locally:

```bash
.venv/bin/python scripts/login_local.py
.venv/bin/python scripts/login_local.py --check
.venv/bin/python scripts/verify_api.py
```

Enter your email and password in the local prompt, never in command arguments or source files. The helper uses a fresh cookie jar, verifies the resulting session with a separate Collection query, and only then replaces the saved session. The revised full password flow, SSO, MFA, CAPTCHA, and mandatory CSRF branches have not all been live-tested; complete any required interactive authentication normally.

Session cookies are stored at `~/.config/readcube-client/session.json` with permissions `0600`. The session-bound verification ledger is stored separately at `~/.config/readcube-client/verified.json`. Neither file is distributed with this repository.

**Production calls require matching verification evidence for the active session and exact endpoint contract.** Source code evidence alone does not unlock an operation. A new session needs its own verification; the public [verification snapshot](docs/verification-results.json) cannot substitute for the private ledger. Unverified operations raise `UnverifiedEndpointError` rather than returning simulated success.

By default, `verify_api.py` verifies the Collection-list read and saves a plan without remote writes. To explicitly authorize its synthetic test workflow:

```bash
.venv/bin/python scripts/verify_api.py --execute \
  --authorized-test-collection 'Codex API Test 2026-10-24'
```

This creates the named private test Collection if needed and tests synthetic records, identifiers, notes, tags, Lists, and a synthetic PDF. It does not delete records or invite other users. Repeated execution can create additional synthetic test objects. Raw responses and local resource IDs remain in the ignored `research/private/` directory.

The extended verification scripts rely on local test-resource files. They are research tools, not a universal one-command onboarding flow for every account.

## Configure and start the MCP server

```bash
cp readcube.example.toml readcube.local.toml
.venv/bin/python -m readcube_mcp --config readcube.local.toml
```

The default configuration leaves the write allowlist empty and enables dry-run. Edit `readcube.local.toml` only for Collections and PDF directories you explicitly authorize.

For a client that accepts `mcpServers` JSON, adapt [examples/mcp-config.json](examples/mcp-config.json) to your absolute Python, project, and configuration paths. The service communicates over **local stdio** by default. An optional single-owner OAuth-protected HTTP entry point is documented in [deploy/RENDER.md](deploy/RENDER.md). Clients start the process on demand. Do not add informational output to protocol stdout.

Read [MCP installation and connection instructions](mcp/README.md) for portable bundles and launchers that do not depend on a client's `cwd` setting. This repository does not install itself into an agent's global configuration. Cloud use needs its own runtime setup, authentication, networking, and a verified MCP integration; copying a Mac-specific JSON configuration is insufficient.

### MCP tool groups

| Group | Tools |
|---|---|
| Fast workflows | `readcube_count_papers`, `readcube_query_library`, `readcube_append_note`, `readcube_workflow_status` |
| Discovery and reading | `readcube_capabilities`, `readcube_list_collections`, `readcube_list_lists`, `readcube_list_smartlists`, `readcube_search_papers`, `readcube_get_paper` |
| Metadata and annotations | `readcube_reader_metadata`, `readcube_get_revisions`, `readcube_get_annotations` |
| References and PDFs | `readcube_add_paper`, `readcube_upload_pdf`, `readcube_import_pdf` |
| PDF reading and search | `readcube_download_pdf`, `readcube_read_pdf`, `readcube_index_fulltext`, `readcube_search_fulltext`, `readcube_prepare_pdf_attachment` |
| Authors and exports | `readcube_author_statistics`, `readcube_normalize_author_names`, `readcube_export_references` |
| Batch metadata | `readcube_batch_update_metadata` |
| Notes and tags | `readcube_update_notes`, `readcube_update_tags` |
| Lists | `readcube_create_list`, `readcube_rename_list`, `readcube_move_list`, `readcube_manage_list_item`, `readcube_delete_list` |
| Smart Lists | `readcube_create_smartlist`, `readcube_update_smartlist`, `readcube_delete_smartlist` |
| Annotation writes | `readcube_create_annotation`, `readcube_update_annotation`, `readcube_delete_annotation` |
| Reference deletion | `readcube_delete_paper` |
| Synchronization | `readcube_sync_library`, `readcube_watch_library` |

Reads may execute directly once verified. Writes default to `dry_run=true`; execution requires `authorized=true`, `dry_run=false`, and a matching local Collection allowlist. Deletion additionally requires separate human confirmation and the exact text `DELETE <resource_id>`. Tool arguments do not replace human authorization.

PDF **upload/import** tools require a nonempty `upload_roots` setting. Original downloads and reading do not require upload permissions. Returned HTTPS upload destinations must match `upload_hosts`; ReadCube cookies are not sent to S3.

## Python SDK example

```python
from readcube_client import ReadCubeClient, Settings

settings = Settings.from_toml("readcube.local.toml")
with ReadCubeClient(settings) as client:
    collections = client.list_collections()
    matches = client.find_by_doi("10.1038/nature12373", "COLLECTION_ID")

    # Build a plan without sending a remote write.
    plan = client.update_notes("COLLECTION_ID", "ITEM_ID", "Reading summary")
    print(plan.model_dump_json())
```

After explicit human authorization, an SDK write uses `WriteAuthorization(collection_id=..., authorized=True)` and `dry_run=False`; the configuration must also allow that Collection. Notes and `set` tags replace their entire fields, so read existing values before preparing an update.

SDK `search()` traverses the complete selected library, including for import deduplication. MCP `readcube_search_papers` reuses the same private index as `readcube_query_library` and attaches `_readcube_cache` provenance to each raw result; use `refresh=true` or `max_age_seconds=0` for a new scan. It retains its legacy list output, so use `readcube_query_library` for bounded results and zero-match counts. Omitting `collection_id` searches all accessible Collections. Multiple DOI or PDF-hash matches return `needs_review=true`; the client does not automatically merge or delete duplicates. PDF import uses SHA-256 scanning and a session/Collection-scoped recent-ID cache with independent GET checks. Server `merge=true` does not guarantee uniqueness, and concurrent imports remain subject to races.

For annotations, `PageNote` and `TextHighlight` validate the reviewed outgoing shapes. Pages are zero-based. Coordinates use original, unrotated page units with a bottom-left origin; rectangles are `[x, y, width, height]`. Provide the attached PDF's actual SHA-256. Rotated, cropped, unusual user-unit, and cross-page geometry is not inferred.

## CLI

```bash
.venv/bin/python -m readcube_client capabilities
.venv/bin/python -m readcube_client collections
.venv/bin/python -m readcube_client search '10.1038/nature12373' --field doi
.venv/bin/python -m readcube_client --config readcube.local.toml add COLLECTION_ID '10.1038/nature12373'
```

The last command defaults to a plan. Remote writes require `--execute --authorize-collection COLLECTION_ID` and the configuration allowlist. Deletion also requires `--confirm-delete 'DELETE ITEM_ID'` (or the exact List ID). Outputs are JSON; errors return `ok=false` with a nonzero exit code.

## Configuration and error handling

Configuration precedence is environment variables > `.env` > TOML > defaults. Use [readcube.example.toml](readcube.example.toml) or [.env.example](.env.example). Array-valued environment variables use JSON:

```bash
export READCUBE_WRITE_COLLECTIONS='["AUTHORIZED_COLLECTION_ID"]'
export READCUBE_UPLOAD_HOSTS='["sync.readcube.com","s3.amazonaws.com"]'
export READCUBE_UPLOAD_ROOTS='["/absolute/path/to/authorized/pdfs"]'
```

Only GET requests are retried. The client honors `Retry-After`; waits longer than 60 seconds are returned to the caller as an error. POST, PATCH, DELETE, and storage PUT are never retried automatically. Invalid envelopes, interrupted pagination, authentication failures, and unverified requests raise explicit errors. Request logs and exceptions omit session values, response bodies, and signed upload URLs.

## Validation and packaging

v0.3.2: **228 local tests passed, 2 opt-in tests skipped**. Pagination recovery is covered for changed totals, missing cursors, duplicate page entries and repeated failures that must not issue an import write. Read-only scans of tPBM and My Papers passed on October 29; the originally reported transient error was not reproduced in those scans.

Recorded validation for v0.3.1: **224 local tests passed, 2 opt-in integration tests skipped**, plus **25 live stdio checks** on October 26. Original PDF download/hash validation, text reading/search, authors, all three export formats, and two-record metadata update/restoration passed. Writes stayed in the dedicated test library. Native ChatGPT attachment upload was not tested in the October 26 validation. See [live results and timings](docs/v0.3.1-live-validation.md). Mock tests never promote real operations to VERIFIED. See [performance validation](docs/performance.md) for measurements and limits.

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check readcube_client readcube_mcp scripts tests
.venv/bin/python scripts/smoke_mcp.py --config readcube.local.toml
.venv/bin/python -m build
.venv/bin/python scripts/build_mcp_bundle.py
```

Live integration tests require explicit opt-in through `READCUBE_RUN_INTEGRATION=1` and `READCUBE_TEST_COLLECTION`. Packaging produces `dist/readcube-mcp-0.3.3.zip` without credentials, plus a separate ignored `mcp.local.json` for the current machine. The bundle includes `tools.json` with all tool schemas.

## Documentation and limitations

- [API reference](docs/readcube-api.md): contracts, fields, examples, and verification status.
- [Reverse-engineering report](docs/reverse-engineering-report.md): sources, observed failures, live checks, and remaining limits.
- [Endpoint table](docs/api-table.md) and [sanitized verification results](docs/verification-results.json).
- [MCP deployment guide](mcp/README.md).

Remaining limits include special authentication branches, shared/read-only role matrices, conditional writes, attachment types and subscription/size limits, and unusual annotation geometry. Synchronization uses complete scans with local diffs; notifications do not provide a durable server delta cursor. A missing item may reflect permission or indexing changes rather than deletion. The project downloads authorized existing attachments; it does not automatically fetch unattached publisher full text or bypass authentication, subscriptions, access controls, or rate limits.
