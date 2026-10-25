# ReadCube Papers API Reverse-Engineering Report

Research dates: **October 24–25, 2026**. All authenticated work used the account owner's session. Writes were restricted to the explicitly authorized private Collection `Codex API Test 2026-10-24`; production references were not modified. No CAPTCHA, MFA, access-control, or rate-limit bypass was used.

## Findings

The SDK catalog contains **38 operations and composite workflows with live request and semantic-check evidence**. The MCP server exposes 27 tools. Verified cases include DOI/PMID import, metadata and user-data updates, Lists/Smart Lists, PDF creation and association, primary-file selection, sticky-note CRUD, single-page highlight creation, auxiliary reads, and Bayeux notifications with full-scan recovery.

The results cover the documented inputs and the tested account, not every role, file type, parameter, or authentication branch. Notifications do not provide an established durable delta cursor.

## Public sources reviewed

| Source | Pinned version | Implementation examined | Evidence scope |
|---|---|---|---|
| [API blog](https://blog.hxgpark.com/posts/ReadCubePapersAPI/) | May 21, 2022 | Login form, GET requests, notes PATCH, Bayeux | Historical explicit contracts, not current success proof |
| [Python project](https://github.com/YusukeKimata-Moo/readcube-papers-skill/tree/38e35f4089f720560724537be764685294098e73) | Commit `38e35f4089f720560724537be764685294098e73` | `scripts/readcube_papers.py`: login/get_items/get_item/get_annotations/search/_parse_item | Read implementations; no DOI/PDF write implementation |
| [Overleaf Gist](https://gist.github.com/MichalPt/0d08085321d03a63aca07720785849c8/aa97173f59786b759c73cd71ced261c3fe97e011) | Revision `aa97173f59786b759c73cd71ced261c3fe97e011`, Papers 5.0.13 noted | `readleaf.user.js`: fetchItems, List URLs, scroll_id, nested metadata to BibTeX | List item routes, pagination, and field usage |

Actual source was examined rather than relying on README claims. Two historical Joplin TypeScript links returned 404 and were not treated as reproducible code. Downloaded third-party scripts were not executed.

Official [release notes](https://about.readcube.com/release-notes/) and [metadata guidance](https://about.readcube.com/help-center/metadata-resolving-incomplete-records/) provided product context, not proof of private HTTP formats. API findings prioritize reviewed frontend code and authorized live requests.

## Current frontend and source anchors

The old entry `https://www.readcube.com/papers/` returned HTTP 403 to a direct request; it was not bypassed. Public HTML and JavaScript from `https://app.readcube.com/` were accessible. Source retrieval and authenticated API verification were separate steps.

Starting from the HTML-referenced `main-UTNWQQUS.js`, 47 entry/chunk assets were recursively retrieved only through explicit `chunk-*.js` references. REST paths were not enumerated or guessed. No sourceMappingURL footer was found, and no public source map was claimed.

| Asset | Main evidence |
|---|---|
| `main-UTNWQQUS.js` | HTTP interceptor, common parameters, withCredentials; SHA-256 `be26f036c79dcd79c298054f5b2b66c12d5ed952dc829c4cbf51f24d3d5a121f` |
| `chunk-QD3Q3KF7.js` | Version 5.4.24, base URLs, Collection/Item/List/Smart List APIs, upload PUT, Bayeux, pagination |
| `chunk-JCLW3CJS.js` | Identifier import, PDF hashing, upload initialization/poll/reassociation, annotation conversion, Collection form |

Complete asset URLs and hashes are in `research/public-assets.json`. Endpoint sources and character offsets are in `readcube_client/endpoints.json`; offsets refer to pinned raw JavaScript, not line numbers. `scripts/build_catalog.py` checks reviewed source needles. Frontend changes require renewed review, not automatic evidence promotion.

Additional explicitly referenced public assets were reviewed on October 25: viewer-core 13.7.0, the authentication page, and its authentication JavaScript. The viewer's decoded SHA-256 was `9b1e6d6e6b50dbc97d6346abd70f674dd147aed99979073ee8eaef6976c95b38`.

Complete third-party frontend files remain ignored research caches under `research/sources/`; they are not shipped in the wheel. No hidden browser session was parsed or exported.

## Initial live verification: October 24

The browser showed an authenticated session but did not expose Network/HAR or session export through the available tooling. The owner chose the local interactive login helper and entered credentials manually. Cookies remained in `~/.config/readcube-client/session.json`, outside source files, reports, and logs.

Authenticated Collection reads succeeded, then the owner authorized creation of the private test library. Expected writes were saved as dry-run plans before execution. No invitations were sent. The generated PDF contained one synthetic sentence, not private or published full text.

| Test | Observed verification |
|---|---|
| Collections, Lists, items, get_item | HTTP 200, valid resource identities and envelopes |
| Forced size=1 pagination | Two valid records, three GETs including an empty terminal page; no duplicate IDs |
| DOI import | Identifier retained in a separate item GET; duplicate detection checked |
| PMID import | Separate POST and GET, merged into the existing test reference |
| Manual metadata creation/update | Synthetic title created and updated, independently read back |
| Notes and set/add/remove tags | Exact notes and tag-set readback after each write |
| List creation/rename/membership | Separate List/item queries, with bounded indexing-propagation waits |
| PDF association | S3 PUT 200, pending completion, reassociation, independent hash confirmation |
| Single reference and List deletion | Exact targets separately approved, then tombstone/absence confirmed |
| Annotation read | Valid initially empty array; no geometry inferred from that empty result |
| Local diff | Two complete scans agreed, without false additions/changes/missing items |
| MCP stdio | Real subprocess initialize/list_tools/capabilities and authenticated query |

The first PDF's hash was `059f5749255d5252765a0995216216968e733f6a013fb2bbc0b21f3f31abb690`. Signed URLs were not retained. An initially unknown upload hostname caused the client to stop; only after identifying the exact authenticated response host `s3.amazonaws.com` was that host added to the local allowlist and retested.

The first end-to-end run failed on immediate List membership readback, and initial immediate DOI deduplication missed a newly imported record. These failures are retained. Subsequent observations and frontend refresh delays support eventual search-index consistency. The fix uses bounded read-only polling, no repeated mutations, and per-instance recent identifier IDs checked through GET. Later membership and duplicate checks passed. Server `merge=true` remained enabled, without being treated as a complete uniqueness guarantee.

Only individually approved synthetic objects were deleted. The library, DOI record, and earlier test objects were retained for audit. Sanitized public outcomes are in `docs/verification-results.json`; raw responses, local resource IDs, and delete previews remain ignored under `research/private/`. Public results exclude cookies, session fingerprints, private library contents, and signed URLs.

## Conflicts and implementation choices

| Conflict | Resolution |
|---|---|
| Blog `scoll_id` vs implementations `scroll_id` | Use the source- and live-confirmed `scroll_id` |
| Historical sync Collection route vs current services route | Use services/collections; record the historical 301 migration separately |
| Historical notes PATCH vs current set_notes | Use verified dedicated set_notes; do not assume equivalence |
| Flattened helper fields vs raw nested records | Preserve article/ext_ids/user_data and unknown fields |
| Manual metadata vs identifier creation | Separate create_item and DOI/PMID contracts |
| Assumed multipart PDF upload | Use observed hash initialization, raw PUT, polling, and reassociation |
| Historical WebSocket clientId dependency | Empty HTTP client_id worked; WebSocket still requires its own handshake |

## SDK and MCP implementation

The SDK uses httpx, pydantic, and pydantic-settings. It provides scoped cookies, configurable timeouts, GET-only retry, pagination validation, JSON CLI output, dry-run plans, write allowlists, and separate deletion confirmation. Explicit research mode is separate from the production surface; MCP imports only production code.

Runtime availability requires a session fingerprint and exact contract hash. A successful response must also pass a research semantic check before promotion. Unit-test mocks do not create real VERIFIED evidence.

The initial release had 48 local tests, two live read-only integration tests, and 16 MCP tools. The extended release has **149 passing local tests, two passing live read-only integration tests, and 27 tools**, plus successful lint and real stdio checks. Coverage includes authentication boundaries, pagination consistency, retry behavior, protocol failures, protected snapshots, file scope/host checks, evidence gating, annotation shapes, deduplication/cache recovery, Bayeux acknowledgement/heartbeat/recovery, and MCP schemas/errors.

No agent-wide configuration was automatically modified. The generated local MCP configuration was tested from outside the project directory. A credential-free bundle was extracted, installed independently, and connected through stdio. Its private-file exclusions and executable launchers were checked.

## Extended verification: October 25

| Previously unresolved area | Completed checks | Remaining boundary |
|---|---|---|
| Authentication state | Expired-cookie filtering, atomic saving, fresh login jar, independent verification, sanitized failure categories; existing session read succeeded | Revised complete password, SSO/MFA, and mandatory-CSRF flows not all live-tested |
| Annotations | Sticky note and single-page highlight created with exact field readback; note text/color updated; separately approved note deleted, highlight retained | bulk_single item/annotation IDs distinguished; viewer-core supplied coordinate evidence; no browser visual-position check |
| Notifications | JSONP handshake, WSS subscription, heartbeat/connect acknowledgements, controlled item-updated event, disconnected-change recovery | Notification-assisted full scans, no durable replay cursor |
| PDF variants | Fresh upload_file created a record; second PDF became a supplement; explicit primary-file switch read back | Attachment metadata uses sha256; size/plan/non-PDF limits not established |
| Smart Lists | Create/read/update saved name/query; approved deletion followed by GET 404 and list absence | Complex queries, roles, and sharing not exhausted |
| Auxiliary reads | reader_metadata DOI agreement; revisions array parsed | Tested revisions array was empty; no recovery/delta semantics inferred |

Detailed source notes are retained in `research/annotation-findings.md`, `research/realtime-findings.md`, and `research/auth-findings.md`. These original research appendices are in Chinese; the usage documentation, API reference, and this report are in English.

### Observed failures and fixes

A supplemental PDF was saved successfully but the original client readback check rejected it: attachment entries used `sha256`, while the old check inspected only `hash`. The corrected check verified the same attachment and the primary-file switch.

Repeated identical PDF import with server `merge=true` still produced two matching records. The client therefore added complete-library SHA-256 scanning and a session/Collection-scoped recent-ID cache with independent GET checks. After the fix, a live duplicate test returned `needs_review=true`, two candidates, and zero writes. Duplicate test objects were retained; no unapproved bulk cleanup occurred. Concurrent import still lacks transactional uniqueness.

Smart List deletion succeeded, but the initial verifier expected a tombstone and then exited on GET 404. Independent GET 404 and List absence subsequently confirmed deletion without repeating DELETE. The exact successful DELETE status had not been persisted; the snapshot honestly retains `http_status=null` and records that the request had passed the client's 2xx/JSON guard. It does not invent a 200. The verifier now handles tombstones/404 and saves audit evidence immediately after mutations.

## Remaining limits

1. **Special authentication:** the active session and current public password form are confirmed, but SSO, MFA, CAPTCHA, forced authenticity_token/CSRF, and the revised full password login are not all live-tested. No independent refresh-token contract was established. The general SDK login method remains explicitly UNVERIFIED; normal reauthentication is required when a session expires.
2. **Durable incremental synchronization:** real events and gap recovery passed, but no durable delta/replay cursor was found. Reconnection, periodic, and final reconciliation use complete scans; indexing visibility delays still exist.
3. **Attachment and annotation edge cases:** non-PDF attachments, plan/size limits, rotated/cropped/user-unit pages, and cross-page highlights remain unverified. Single-page fields were read back exactly, not visually overlaid in a browser. Duplicate candidates require human review.
4. **Permissions and concurrency:** no dedicated shared/read-only/organization-restricted test identities were available, and no roles or invitations were changed. Deep List limits and conditional/concurrent writes lack established verification.
5. **Full server error taxonomy:** bounded retry and protocol behavior are tested locally, but rate limits, 5xx failures, and unauthorized resources were not deliberately provoked.

Further progress requires normal special-authentication evidence, separately authorized permission-matrix accounts, or specific attachment/page samples. Existing authorized tests were completed without modifying production references.
