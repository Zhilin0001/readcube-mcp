# Performance in v0.2.1

Measured on October 25, 2026 using the existing 419-reference library for read-only requests. Note writes ran only in the authorized synthetic test Collection, with exact read-back and restoration of the original notes. These are local tool timings under the observed network conditions, excluding agent reasoning and user approval time; they are not latency guarantees.

## Observed results

| Operation | Before | After | Remote requests after |
|---|---:|---:|---:|
| Repeated legacy title search | 7.20 s | 0.012 s | 0 (shared cache) |
| Compact title search, warm | Already cached at about 0.010 s | 0.001–0.002 s | 0 |
| Append-note preview | 1.42 s | 0.41 s | 1 |
| Append note and independently verify | Not measured | 2.14 s | 3 |
| Repeat identical append | Not measured | 0.42 s | 1; no duplicate write |
| Search immediately after note append | Previously invalidated the entire index | 0.003 s | 0 |
| Complete fresh 419-item query | 9.23 s, 10 requests | 7.11 s, 9 requests | 9 |
| Live count | Required a full scan in the old MCP | 1.35 s over configured stdio | 1 |

The real configured stdio server reported version 0.2.1 and 31 tools. Across that transport, cached queries took 0.019 s on the first call and 0.002 s on repetition; note preview took 0.386 s. In-process results above measure the same handlers and pool, with request-count instrumentation. Cold timings vary with network conditions; an earlier optimized full scan took 6.20 s.

A title search for `photobiomodulation` returned about 470 KB through the original raw tool. The recommended compact query returned 2.7 KB for five selected results, with the total match count and explicit truncation. Raw search keeps its compatibility list output and remains large; prefer `readcube_query_library` for ordinary interactive use.

## Changes and boundaries

- Reuse up to four exclusive HTTP clients with 60-second keep-alive. Reload configuration and verification evidence and validate saved-cookie expiry and file permissions on every invocation. Server response cookie rotation no longer needlessly discards the connection: the next invocation restores the verified saved cookie jar.
- Both MCP search tools share a private, session- and contract-scoped index. Cache age and source are explicit; the default freshness window is 300 seconds. `refresh=true` or `max_age_seconds=0` forces a new complete scan. The first query after expiry or cache-format migration still scans the library; it is not instantaneous. SDK import deduplication remains a fresh server scan.
- Use `readcube_count_papers` for a current total. It asks the verified item endpoint for one record and reads the reported total; it does not compute reading or annotation counts.
- Stop pagination at a consistent exact total instead of fetching the final empty page. Reject changing/invalid totals, duplicate IDs, missing cursors and incomplete scans.
- Concurrent cold queries share one scan. A separate scan lock lets notes run while that scan is in flight. Local mutation generations prevent a scan from overwriting a newer note; one overlap triggers one rescan, repeated overlaps raise an explicit error.
- Notes use fresh GET → write → GET, preserve previous text, and skip an identical append. Successful read-back updates just that indexed item and preserves the original full-scan timestamp; uncertain writes invalidate the index. Direct replacement writes patch only confirmed response values. Local note operations serialize within a Collection; edits by other applications still have no server compare-and-swap protection.
- Sync/watch full scans also refresh the shared search index, so a reported sync change is not hidden behind an older local query cache.
- Compact results bound note previews to 320 characters. Full notes remain searchable and retrievable through `readcube_get_paper`.

## Reproduce

```bash
.venv/bin/python scripts/benchmark_mcp.py \
  --config readcube.local.toml --collection COLLECTION_ID
.venv/bin/python scripts/smoke_mcp.py --config readcube.local.toml
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check readcube_client readcube_mcp tests scripts
```

The benchmark defaults to reads. Optional `--note-collection` and `--note-item` add dry-run timings. `--execute-notes` requires explicit authorization, an allowlisted synthetic `Codex API Test ...` Collection, and uses a private backup plus verified restoration. Output contains timings/counts, not cookies or paper contents. The default report path is ignored `.state/performance/optimized.json`.

Validation at delivery: 187 tests passed, two opt-in integration tests skipped in the offline suite; authenticated read, count, cache, note append/idempotence/restoration and configured stdio checks passed separately. Runtime pooling, session/permission invalidation, cache refresh failures, concurrent queries/writes and unchanged live import deduplication have regression coverage.
