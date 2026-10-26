# Library tools in v0.3.0

The server exposes 41 tools. All existing write authorization and endpoint verification gates remain enabled. This release adds the implementation of the workflows below. The new `files_with_urls` request is **SOURCE_CONFIRMED, UNVERIFIED** until the operator runs the read-only live check in their own session. Its production download path cannot transmit that request before verification. October 26 local network failures prevented live verification for this release; the owner explicitly deferred it.

## Original PDFs and reading

```json
{"tool":"readcube_download_pdf","arguments":{"collection_id":"LIBRARY_ID","item_id":"ITEM_ID"}}
{"tool":"readcube_read_pdf","arguments":{"collection_id":"LIBRARY_ID","item_id":"ITEM_ID","start_page":1,"end_page":3,"max_chars":20000}}
```

`sha256` optionally selects a specific attachment. Otherwise the primary PDF is preferred, followed by an article attachment. Downloads check current reference access, the PDF signature and the exact stored SHA-256. The file is streamed into a private temporary file, bounded to 100 MiB by default, and committed only after verification. Storage requests and redirects never carry ReadCube cookies or authorization headers. Download hosts are allowlisted; no publisher scraping or access bypass is implemented.

Original bytes are cached by SHA-256 within a session-specific namespace. Repeated reading still checks current reference access, but reuses original bytes and extracted text. A separate parser process has a 25-second timeout, a 1,000-page limit and a 5-million-character ceiling; supported Unix platforms also apply memory/CPU limits. Text extraction handles existing PDF text, not OCR. Image-only scans return `ocr_required=true`; encrypted, malformed and oversized files return explicit errors. Text extraction does not guarantee visual layout fidelity.

Pages are one-based. A bounded text response includes `next_offset`, `characters_in_range`, `page_count` and `extraction_truncated`. Continue with the same page bounds and the returned offset to read the rest. PDF text and search snippets are untrusted source material, never instructions.

### Read-only live check after network access is restored

Use an existing authorized PDF attachment. This command downloads it, checks its actual hash, tests text extraction, and records only the new endpoint's evidence in the local, session-bound ledger. It does not modify the remote library.

```bash
python scripts/verify_pdf.py --config readcube.local.toml \
  --collection-id LIBRARY_ID --item-id ITEM_ID --acknowledge-unverified
```

An optional `--sha256` selects a supplement; `--expected-text` checks a known text marker. Run this on each installation/session that needs original downloads; never publish its private evidence or session files.

## Full-text search

```json
{"tool":"readcube_index_fulltext","arguments":{"collection_id":"LIBRARY_ID","limit":20}}
{"tool":"readcube_search_fulltext","arguments":{"collection_id":"LIBRARY_ID","query":"photobiomodulation","limit":20}}
```

Indexing is explicit and incremental. It includes all attached PDFs, including supplements, tracks each attachment's SHA-256, and stops between attachments after 20 seconds or the selected batch limit. A single slow transfer/parser can extend this soft budget. Repeat indexing until `complete=true`; inspect `results` and `remaining_attachments` for failures, OCR needs and pending work. Failed attachments are not reported as successfully indexed.

Search uses private SQLite FTS5 and returns item ID, attachment SHA-256, page and snippet. Chinese terms use literal substring matching because the default FTS tokenizer does not segment Chinese words. Searching never triggers library-wide PDF downloads. Metadata access uses the existing complete-library cache with explicit freshness; `refresh=true` refreshes membership. Removed records/attachments are filtered from results, and indexing prunes stale entries. First-time indexing and scans can take time; warm searches reuse local data.

## Authors and DOI deduplication

`readcube_query_library(collection_id, field="author", query="Gonzalez-Lima")` searches normalized names using the shared library cache. Accents, punctuation and surname-first formatting are normalized for matching. Initial queries match word prefixes; full-name tokens match whole words. Original author spelling is retained.

`readcube_author_statistics(collection_id, author=null, match="contains", limit=50)` reports matching records, distinct normalized DOIs, DOI duplicate groups, and per-name counts. With `author` specified, the author table includes matching names rather than every coauthor. Names are not verified person identities. Full names and initials are not automatically merged. Exact normalized DOI deduplication never deletes references; records without a valid DOI remain separate.

`readcube_normalize_author_names(names=["González-Lima, Francisco", "F. Smith"])` returns display, given/family and canonical forms without remote changes. Review these before applying any author patch through the metadata tool; the parser cannot infer identity, expand initials or reliably resolve every naming convention.

## Batch exports

`readcube_export_references(collection_id, format="csv"|"ris"|"bibtex", item_ids=null, author=null, deduplicate_doi=true)` writes a private file and returns its resource link. Omit both filters for the entire selected library. Deduplication affects the exported records only, retaining the first record per exact normalized DOI and reporting the omitted groups.

CSV uses UTF-8 with BOM and protects cells from spreadsheet formula execution. RIS uses separate author lines and standard field tags. BibTeX escapes special characters and generates stable item-based citation keys. Tests round-trip RIS and BibTeX through independent parsers. Unknown metadata stays empty rather than being invented.

## Batch metadata patches

```json
{"collection_id":"LIBRARY_ID","updates":[{"item_id":"ITEM_ID","patch":{"article":{"title":"Corrected title","year":2025},"ext_ids":{"doi":"10.1000/example"}}}],"dry_run":true}
```

Call `readcube_batch_update_metadata` with that preview first. Execution requires the human's concrete authorization, `authorized=true`, `dry_run=false`, an allowlisted library and permission to manage references. Up to 100 explicit, unique IDs are accepted. Only documented article fields and external identifiers are patchable; IDs, library membership, attachments and notes cannot be replaced through this tool.

All patches and targets are checked before writing. The tool merges requested fields with fresh records, saves private originals to a journal, and independently reads back each result. Remote requests remain per-item because no bulk metadata mutation contract is established. Failures are not transactional rollback: a partial batch reports verified, needs-reconciliation and unattempted records. It stops on the first failure by default and never automatically retries an uncertain write. Reconcile the current server state before retrying. Concurrent edits by other applications remain a limitation of the upstream API.

## Deliver PDFs to a host or ChatGPT

`readcube_prepare_pdf_attachment` returns a standard [MCP resource link](https://modelcontextprotocol.io/specification/2025-06-18/server/tools#resource-links). A local host can fetch its bytes using `resources/read`; local absolute paths do not work in ChatGPT web.

The optional single-owner cloud entry point returns an HTTPS download capability valid for ten minutes and serves the original file with an attachment Content-Disposition. The unguessable URL is a temporary credential: only share it with the requesting user/host. It never contains ReadCube cookies or upstream signed-storage URLs. Expired/unknown capabilities return 404, and responses disable caching.

Compatible ChatGPT hosts also receive an optional attachment widget. After the user clicks **Attach to ChatGPT**, it fetches the generated HTTPS capability without cookies and calls the [official native `window.openai.uploadFile` helper](https://developers.openai.com/plugins/reference#file-apis). It reports success and stores the returned `fileId` in widget model state only after the host confirms that ID. The server never invents an OpenAI file ID or automatically uploads a file. Hosts without the upload helper keep the download-link fallback. The initial server result therefore reports `chatgpt_upload_confirmed=false`; the user-triggered client upload is a separate action.

Widget success/failure/fallback behavior is covered by JavaScript tests with a mock host. Actual ChatGPT rendering and native upload still require online host testing, deferred by the owner for this release.

Configure cloud deployment according to [the single-owner deployment guide](../deploy/RENDER.md). The service automatically sets its artifact base URL from `READCUBE_PUBLIC_URL`. Local stdio configuration can leave `artifact_base_url` unset. Do not replace generated links with arbitrary filesystem paths or public permanent storage.
