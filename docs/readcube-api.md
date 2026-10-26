# ReadCube Papers Web API

Discovery and verification dates: **October 24–25, 2026**. Reviewed public frontend: **5.4.24**. These are unofficial contracts, documented from explicit source references and authorized requests.

## Evidence and runtime availability

- `VERIFIED`: a real request succeeded and its semantic check passed; writes generally have independent readback.
- `SOURCE_CONFIRMED`: an explicit implementation exists in reviewed source. This alone does not establish current account access.
- `INFERRED`: a supported inference, not an executable contract in this project.
- `UNKNOWN`: no complete reviewed contract.
- `UNVERIFIED`: runtime verification state, which can coexist with source confirmation.

Evidence and availability are separate. Production calls require an active-session ledger entry matching the endpoint contract's SHA-256. The public [verification snapshot](verification-results.json) is sanitized research evidence, not an unlock file.

## Hosts and common parameters

| Host | Origin |
|---|---|
| services | `https://services.readcube.com` |
| sync | `https://sync.readcube.com` |
| push | `https://push.readcube.com/bayeux` / `wss://push.readcube.com/bayeux` |

The frontend sends `Accept: application/json`, `client=webapp`, `client_id`, and `client_version=5.4.24`, with cross-origin cookies. The SDK uses an empty HTTP `client_id`; the verified HTTP operations worked without an active WebSocket connection. This does not remove the Bayeux handshake requirement.

Cookies retain domain, path, secure, and expiry attributes and are stored locally in a `0600` file. Historical names include `_readcube-login_token`, `_readcube_session`, and `user_web_token`; do not hard-code an exact required set. Passwords are not persisted. Redirects are not automatically followed.

## Endpoint catalog

Generated from `readcube_client/endpoints.json` and the local verification ledger. `FLOW` denotes a composite workflow, not an additional HTTP endpoint. A separate copy is available in [api-table.md](api-table.md).

| Operation | Method | Host | Path | Recorded status |
|---|---|---|---|---|
| `list_collections` | GET | `services` | `/collections` | VERIFIED / SOURCE_CONFIRMED |
| `list_lists` | GET | `sync` | `/collections/{collection_id}/lists` | VERIFIED / SOURCE_CONFIRMED |
| `list_items` | GET | `sync` | `/collections/{collection_id}/items` | VERIFIED / SOURCE_CONFIRMED |
| `list_list_items` | GET | `sync` | `/collections/{collection_id}/lists/{list_id}/items` | VERIFIED / SOURCE_CONFIRMED |
| `get_item` | GET | `sync` | `/collections/{collection_id}/items/{item_id}` | VERIFIED / SOURCE_CONFIRMED |
| `create_collection` | POST | `services` | `/collections` | VERIFIED / SOURCE_CONFIRMED |
| `create_item` | POST | `sync` | `/collections/{collection_id}/items` | VERIFIED / SOURCE_CONFIRMED |
| `import_identifier` | POST | `sync` | `/collections/{collection_id}/items` | VERIFIED / SOURCE_CONFIRMED |
| `update_metadata` | PATCH | `sync` | `/collections/{collection_id}/items/{item_id}` | VERIFIED / SOURCE_CONFIRMED |
| `update_notes` | POST | `sync` | `/collections/{collection_id}/items/{item_id}/set_notes` | VERIFIED / SOURCE_CONFIRMED |
| `set_tags` | POST | `sync` | `/collections/{collection_id}/items/{item_id}/set_tags` | VERIFIED / SOURCE_CONFIRMED |
| `add_tags` | POST | `sync` | `/collections/{collection_id}/items/{item_id}/add_tags` | VERIFIED / SOURCE_CONFIRMED |
| `remove_tags` | POST | `sync` | `/collections/{collection_id}/items/{item_id}/remove_tags` | VERIFIED / SOURCE_CONFIRMED |
| `delete_item` | DELETE | `sync` | `/collections/{collection_id}/items/{item_id}` | VERIFIED / SOURCE_CONFIRMED |
| `get_annotations` | GET | `sync` | `/collections/{collection_id}/items/{item_id}/annotations` | VERIFIED / SOURCE_CONFIRMED |
| `update_annotation` | PATCH | `sync` | `/collections/{collection_id}/items/{item_id}/annotations/{annotation_id}` | VERIFIED / SOURCE_CONFIRMED |
| `delete_annotation` | DELETE | `sync` | `/collections/{collection_id}/items/{item_id}/annotations/{annotation_id}` | VERIFIED / SOURCE_CONFIRMED |
| `create_list` | POST | `sync` | `/collections/{collection_id}/lists` | VERIFIED / SOURCE_CONFIRMED |
| `rename_list` | PATCH | `sync` | `/collections/{collection_id}/lists/{list_id}` | VERIFIED / SOURCE_CONFIRMED |
| `move_list` | PATCH | `sync` | `/collections/{collection_id}/lists/{list_id}` | VERIFIED / SOURCE_CONFIRMED |
| `delete_list` | DELETE | `sync` | `/collections/{collection_id}/lists/{list_id}` | VERIFIED / SOURCE_CONFIRMED |
| `add_to_list` | POST | `sync` | `/collections/{collection_id}/lists/{list_id}/add_items` | VERIFIED / SOURCE_CONFIRMED |
| `remove_from_list` | POST | `sync` | `/collections/{collection_id}/lists/{list_id}/remove_items` | VERIFIED / SOURCE_CONFIRMED |
| `add_file` | POST | `sync` | `/collections/{collection_id}/items/{item_id}/add_file` | VERIFIED / SOURCE_CONFIRMED |
| `upload_file` | POST | `sync` | `/collections/{collection_id}/items/upload_file` | VERIFIED / SOURCE_CONFIRMED |
| `uploads_pending` | GET | `sync` | `/collections/{collection_id}/items/uploads_pending` | VERIFIED / SOURCE_CONFIRMED |
| `get_revisions` | GET | `sync` | `/collections/{collection_id}/items/{item_id}/revisions` | VERIFIED / SOURCE_CONFIRMED |
| `list_smartlists` | GET | `sync` | `/collections/{collection_id}/smartlists` | VERIFIED / SOURCE_CONFIRMED |
| `get_smartlist` | GET | `sync` | `/collections/{collection_id}/smartlists/{smartlist_id}` | VERIFIED / SOURCE_CONFIRMED |
| `create_smartlist` | POST | `sync` | `/collections/{collection_id}/smartlists` | VERIFIED / SOURCE_CONFIRMED |
| `update_smartlist` | PATCH | `sync` | `/collections/{collection_id}/smartlists/{smartlist_id}` | VERIFIED / SOURCE_CONFIRMED |
| `delete_smartlist` | DELETE | `sync` | `/collections/{collection_id}/smartlists/{smartlist_id}` | VERIFIED / SOURCE_CONFIRMED |
| `set_primary_file` | POST | `sync` | `/collections/{collection_id}/items/{item_id}/set_primary` | VERIFIED / SOURCE_CONFIRMED |
| `create_annotation` | POST | `sync` | `/collections/{collection_id}/bulk_single` | VERIFIED / SOURCE_CONFIRMED |
| `import_pmid` | POST | `sync` | `/collections/{collection_id}/items` | VERIFIED / SOURCE_CONFIRMED |
| `upload_pdf_flow` | FLOW | `sync` | `/collections/{collection_id}/items/{item_id}/add_file` | VERIFIED / SOURCE_CONFIRMED |
| `import_pdf_flow` | FLOW | `sync` | `/collections/{collection_id}/items/upload_file` | VERIFIED / SOURCE_CONFIRMED |
| `reader_metadata` | GET | `services` | `/reader/metadata` | VERIFIED / SOURCE_CONFIRMED |
| `watch_changes` | FLOW | `push` | `/bayeux` | VERIFIED / SOURCE_CONFIRMED |

Every wrapped path has an explicit source. Annotation creation was cross-checked against `bulk_single` in the frontend and the viewer's annotation model. Source URLs, versions, dates, and character offsets are in `readcube_client/endpoints.json`; public asset hashes are in `research/public-assets.json`.

## Collections, Lists, and references

`GET services/collections` returns `{"collections":[...]}`. Common fields include `id`, `name`, `description`, `shared`, `organization_id`, `discoverable`, and `user`. Such fields do not replace server-side permission checks. Collection names may be absent or null.

`GET sync/collections/C/lists` returns `{"lists":[...]}`. List fields include `id`, `collection_id`, `name`, `parent_id`, `item_ids`, `deleted`, `created`, `modified`, and `seq`. An absent parent can represent a root List. Smart Lists use their own saved-query endpoints.

### Pagination

```http
GET /collections/C/items?size=50&sort[]=created,asc&client=webapp&client_id=&client_version=5.4.24
GET /collections/C/items?size=50&sort[]=created,asc&scroll_id=OPAQUE_CURSOR&client=webapp&client_id=&client_version=5.4.24
```

Illustrative response:

```json
{
  "status": "ok",
  "items": [{"id":"I","collection_id":"C","article":{"title":"Example"},"ext_ids":{"doi":"10.1234/example"},"user_data":{"tags":[],"notes":""},"files":[]}],
  "scroll_id": "OPAQUE_CURSOR",
  "total": 1
}
```

Read until the stable, nonnegative integer `total` is reached, an empty page arrives, or the cursor is absent. Reaching `total` avoids an unnecessary terminal request; changing totals or receiving excess records raises a pagination error. A missing cursor before the advertised total raises an error. Elasticsearch can reuse a cursor while advancing, so the SDK checks duplicate item IDs and a maximum page count rather than rejecting a repeated cursor alone. Search `query` is sent on the first page only.

A forced live `size=1` test retrieved two valid records in three GETs, including the terminal empty page. The historical blog's `scoll_id` spelling conflicts with the Gist, Python implementation, frontend, and live responses; the implemented parameter is **`scroll_id`**.

A single-reference response is `{"item":{...}}`. The SDK preserves nested and unknown fields:

| Field | Meaning |
|---|---|
| `id`, `collection_id` | Resource identity; use item IDs, not DOIs, in item paths |
| `article` | Title, authors, year, journal, abstract, and other bibliographic data |
| `ext_ids` | DOI, PMID, arXiv, PMCID, and other external identifiers |
| `user_data` | Notes, tags, ratings, and other user fields |
| `files` | Attachment metadata, including `sha256`; additional fields remain intact |
| `list_ids` | List membership |
| `seq`, `deleted` | Change/deletion-related fields; not an established delta protocol |

SDK `search()` performs complete pagination followed by exact normalized DOI/PMID matching or a case-insensitive title substring match. MCP search uses a session- and contract-scoped cache with explicit freshness metadata; import deduplication still uses the live SDK method. `count_items()` reads the server total using a verified `size=1` request. Complex server query syntax has not been exhaustively verified and is not assumed for deduplication.

## Import identifiers and create metadata records

DOI import uses **top-level `ext_ids`**:

```http
POST /collections/C/items
Content-Type: application/json
```

```json
{"ext_ids":{"doi":"10.1038/nature12373"},"merge":true,"resolve":true,"resolve_files":false}
```

The separately verified PMID variant uses:

```json
{"ext_ids":{"pmid":"23903748"},"merge":true,"resolve":true,"resolve_files":false}
```

Both return `item`, potentially with `merged`. The DOI was independently read back. The PMID test merged into the same test reference, with the identifier and resource identity confirmed by GET.

Manual metadata creation uses another envelope:

```json
{"item":{"item_type":"article","article":{"title":"Synthetic test reference"}}}
```

Optional fields and `item_type` values have not been exhaustively tested. Raw objects remain available rather than being flattened into an allegedly complete bibliographic model.

Before import, the client searches the target library. Existing matches return `{"created":false,"needs_review":false,"matches":[...]}`; multiple candidates set `needs_review=true`. No automatic merge or deletion is performed. `merge=true` is still submitted, but is not a guarantee of uniqueness under indexing delays or concurrent imports. `resolve_files=false` avoids automatically resolving full text from unspecified sources.

## Notes, tags, and metadata updates

| Operation | JSON body | Effect |
|---|---|---|
| `POST .../set_notes` | `{"notes":"Reading summary"}` | Replace the complete notes field |
| `POST .../set_tags` | `{"tags":["review"]}` | Replace the complete tag list |
| `POST .../add_tags` | `{"tags":["temporary"]}` | Add tags |
| `POST .../remove_tags` | `{"tags":["temporary"]}` | Remove the specified tags |
| `PATCH .../items/I` | `{"item":{"article":{"title":"Updated"}}}` | Update reference metadata |

Each returns `{"item":{...}}` and was checked through independent GETs. The SDK uses the frontend's dedicated `set_notes` route; the historical notes PATCH variant was not independently retested.

Read existing notes and tags before preparing replacements. No verified ETag or version-conditional write mechanism is implemented, so concurrent edits may overwrite changes. An instruction to append a summary is not authorization to discard existing notes.

## Lists and Smart Lists

Ordinary List creation:

```json
{"list":{"id":"CLIENT_GENERATED_UUID","collection_id":"C","name":"Reading","parent_id":null}}
```

Move an existing List with `PATCH /collections/C/lists/L` and `{"list":{"id":"L","collection_id":"C","parent_id":"P"}}`; use a null parent to return to the root. This partial patch preserves the List name and memberships. The frontend navigation `moveList` and Edit List form confirm the contract. A dedicated test-library move and return-to-root were read back on October 25, 2026. The client checks library membership and prevents hierarchy cycles before writing.

Rename with `PATCH /collections/C/lists/L` and `{"list":{"id":"L","collection_id":"C","name":"Renamed"}}`. Add/remove membership through `POST .../lists/L/add_items` or `remove_items`, with `{"item_ids":["I"]}`. Responses contain `list`. Removing membership does not delete the reference.

Membership indexing can lag behind writes. Verification uses bounded read-only polling, not repeated mutations. Root List CRUD and membership changes were live-tested; deep nesting and cross-library membership were not exhaustively tested.

Smart List CRUD uses `/collections/C/smartlists` and `/collections/C/smartlists/S`. Creation uses:

```json
{"smartlist":{"id":"CLIENT_GENERATED_UUID","collection_id":"C","name":"Methods","query":"methods"}}
```

Updates preserve `id` and `collection_id`. Name/query changes were independently read back. A deleted Smart List may return GET 404. Saved-query storage was verified; all search syntax and sharing roles were not.

## PDFs and attachment association

The verified upload is a multi-step workflow:

1. Validate an authorized local PDF and compute SHA-256 over its raw bytes.
2. `POST /collections/C/items/I/add_file` with:

```json
{"file_name":"synthetic-test.pdf","file_size":687,"primary":false,"hash":"LOCAL_SHA256_HEX","resolve":false,"skip_resolve":true,"merge":false}
```

The size is illustrative and must be computed from the actual file. A known hash may return `item` immediately; otherwise the response contains `upload_id` and `upload_url`.

3. **PUT raw file bytes** to the returned HTTPS URL using `Content-Type: application/pdf`, without extra business query parameters. The tested host was `s3.amazonaws.com`; signed URL paths and query strings are not published or logged. An isolated client prevents ReadCube cookies from being sent to S3.
4. GET `.../items/uploads_pending` and find the entry keyed by upload ID. The reviewed frontend polls at approximately three-second intervals.
5. On `completed`, compare the processed hash to the local digest and POST the same `add_file` body again to associate the attachment.
6. GET the reference and confirm the digest in `files[].sha256` or `primary_file_hash`. A successful storage PUT alone does not prove association.

Unknown upload hosts require an explicit allowlist. Failed processing, unexpected shapes, hash mismatches, and timeouts raise errors. Writes are not automatically retried; inspect state before deciding what to do after a timeout.

`import_pdf` uses the same PUT/pending/reassociation workflow with `POST .../items/upload_file`, `file_name`, `file_size`, `hash`, `resolve=true`, `skip_resolve=false`, `merge=true`, and `user_data.tags=[]`. A fresh synthetic PDF created a reference and passed independent hash readback.

A second synthetic PDF was stored as a supplement. `POST .../items/I/set_primary` with `{"hash":"SHA256"}` changed the primary file, independently confirmed by GET. Default attachment upload uses `primary=false`.

Server `merge=true` did not guarantee a single reference for repeated identical PDFs. The SDK adds complete-library SHA-256 checks and a session/Collection-scoped recent-ID cache, verified by GET. Multiple matches require human review. There is no cross-process transactional uniqueness guarantee. Non-PDF attachments, storage plans, and size limits remain unverified.

## Annotations and highlights

`GET .../items/I/annotations` returns `{"annotations":[...]}` and preserves raw fields. A synthetic PDF was used to create and read back both a sticky note and a single-page highlight, then update and separately authorize deletion of the note.

Creation uses `POST /collections/C/bulk_single`:

```json
{"type":"item","action_name":"add_annotation","data":[{"id":"ITEM_ID","data":{"id":"ANNOTATION_UUID","type":"note","has_note":true,"note":"Synthetic note","page_start":0,"sha256":"PDF_SHA256","color_id":1,"position":[72,720]}}]}
```

The SDK restricts this to one item and one annotation. It checks result length, `saved`, and the returned item ID. `TextHighlight` uses `type=highlight`, equal `page_start`/`page_end`, and `rects=[[x,y,width,height]]`; `text` and `note` are optional.

Pages are zero-based. Coordinates use original unrotated page units with a bottom-left origin. Reviewed color IDs are 1, 2, 3, 4, 5, 6, and 10. Models and conversion helpers are in `readcube_client/annotations.py`. Unsupported types, rotation, crop boxes, user-unit transformations, and cross-page geometry are not guessed. Exact field readback is not a browser visual-position check.

Modification uses `PATCH .../items/I/annotations/A`; `note` and `color_id` were live-verified. MCP patches conservatively permit only `note`, `has_note`, and `color_id`. DELETE uses the same path and requires the exact confirmation `DELETE A`.

## Deletion and authorization

Single-reference deletion uses `DELETE /collections/C/items/I`; a List uses `DELETE /collections/C/lists/L`. Tests deleted one individually approved synthetic reference and ordinary List, then an individually approved synthetic note and Smart List. GET tombstones, 404s, or list absence confirmed the results. No bulk deletion was performed.

Execution requires the operation to be VERIFIED for the current session, the Collection to be in `write_collections`, and a matching `WriteAuthorization(authorized=True)`. Deletion additionally requires `confirmation="DELETE <exact_resource_id>"`. MCP agents must obtain the human's separate deletion authorization; setting tool parameters is not sufficient.

## Synchronization and error handling

The frontend uses Bayeux handshake, `/meta/subscribe`, and `/meta/connect`, with `/production/users/{id}` and `/production/collections/{id}/changes` channels and `sync_client_id` filtering. Live verification covered handshake/subscription/connect acknowledgement, a controlled item-updated event, and recovery of a modification made while disconnected.

`watch_changes`/`watch_library` reconcile through complete scans after connection, notification, gaps, periodically, and at completion. Their mode is `notification_assisted_full_scan`; no durable cursor or replay contract has been established.

`sync_changes` uses `full_scan_local_diff`, returning added/changed/missing/total. It refreshes the shared query index and atomically replaces the fingerprint snapshot only after complete pagination succeeds. A missing item may reflect access, indexing, or concurrent changes rather than proven server deletion.

| Condition | SDK behavior |
|---|---|
| 401 / 403 | `AuthenticationError`; no authentication bypass or automatic login retry |
| 429 / 500 / 502 / 503 / 504 | Bounded GET retry with `Retry-After`; long waits return control to the caller |
| POST/PATCH/DELETE/storage PUT failure | No automatic retry |
| HTTP 200 with non-JSON, unsuccessful status, or error envelope | `ProtocolError` |
| Missing fields, interrupted pagination, or duplicate pages | Explicit error |
| Unverified operation or missing contract | `UnverifiedEndpointError`, also a `NotImplementedError` subclass |

These are client behaviors covered by protocol tests. The real service was not deliberately driven into rate limits, 5xx failures, or unauthorized access; its full error-code set is not claimed to be known.

## Auxiliary reads and authentication state

`reader_metadata(doi)` calls `GET services/reader/metadata?doi=...`, preserves the original `meta`, references, figures, and other fields, and checks the returned canonical DOI. The response contained meta/citations/figures/references/options/supplements/total_pages.

`get_revisions(C,I)` calls `GET sync/collections/C/items/I/revisions` and validates an array. The tested array was empty; this does not establish historical recovery or delta-cursor semantics.

The historical `sync/collections/` returned 301 to `https://services.readcube.com/collections`. This migration is recorded, not implemented as a redirect alias.

`auth.session_status` checks local cookies only. `validate_saved_session` and `login_local.py --check` independently GET Collections and can safely persist cookies updated by the server. Cookie identity changes invalidate old session-bound evidence. No independent refresh-token route is invented; an expired session needs normal reauthentication. The revised complete password login and SSO/MFA/mandatory-CSRF branches were not all live-tested; `ReadCubeClient.login()` remains explicitly unavailable as an unverified general login API.

## Original attachment URLs (v0.3.0)

`GET /collections/{collection_id}/items/files_with_urls` uses repeated `item_ids[]` query parameters, as observed in the frontend `getFilesWithURLs` method. Expected JSON maps each requested item ID to attachment objects containing SHA-256 and a temporary `download_url`. The operation is SOURCE_CONFIRMED and remains UNVERIFIED until a real original download matches the reference hash; see `scripts/verify_pdf.py`. The original frontend download helper also builds `/collections/{collection_id}/items/{item_id}/download?hash=...&file_name=...`, but this release uses the file-URL lookup and never assumes that helper returns JSON.

Storage transfers have separate HTTPS host validation, explicit redirect checks, no inherited cookies or HTTP authentication, bounded streaming, PDF-signature and SHA-256 validation. Generated host resources use separate expiring capability links. See [library workflows](library-tools.md) for the local text, FTS, author and metadata features.
