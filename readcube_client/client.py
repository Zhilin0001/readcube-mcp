import hashlib
import json
import logging
import re
import time
import uuid
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx

from .auth import load_cookies, private_json_write, session_fingerprint
from .config import Settings
from .errors import (
    APIError,
    AuthenticationError,
    AuthorizationError,
    PaginationError,
    ProtocolError,
    TransportError,
    UnverifiedEndpointError,
    UploadPendingError,
)
from .evidence import EvidenceRegistry
from .models import Item, SyncDelta, WriteAuthorization, WritePlan

HOSTS = {"services": "https://services.readcube.com", "sync": "https://sync.readcube.com"}


def normalize_doi(value: str) -> str:
    value = unquote(value.strip())
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value, flags=re.IGNORECASE)
    value = value.strip().casefold()
    if not re.fullmatch(r"10\.\d{4,9}/\S+", value):
        raise ValueError("Invalid DOI")
    return value


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_:-]+", value):
        raise ValueError("Invalid resource identifier")
    return value


class ReadCubeClient(AbstractContextManager):
    """Production client. Only operations in the local verified ledger can transmit requests."""

    def __init__(self, settings: Settings | None = None, *, http: httpx.Client | None = None):
        # httpx INFO logs include signed storage URLs; never emit those as request logs.
        for logger_name in ("httpx", "httpcore", "httpx2", "httpcore2"):
            logging.getLogger(logger_name).setLevel(logging.WARNING)
        self.settings = settings or Settings()
        self._owns_http = http is None
        if http is None:
            cookies = (
                load_cookies(self.settings.session_file)
                if self.settings.session_file.exists()
                else httpx.Cookies()
            )
            self.http = httpx.Client(
                cookies=cookies,
                timeout=self.settings.timeout,
                limits=httpx.Limits(
                    max_connections=8, max_keepalive_connections=4, keepalive_expiry=60
                ),
                follow_redirects=False,
                headers={"Accept": "application/json"},
            )
        else:
            self.http = http
        self.session = session_fingerprint(self.http.cookies)
        self.registry = EvidenceRegistry(self.settings.verification_file, self.session)
        self._research = False
        self._last_request = 0.0
        self.audit: list[dict] = []
        self._recent_identifiers: dict[tuple[str, str, str], str] = {}
        self._recent_pdf_imports: dict[tuple[str, str], str] = {}

    def close(self):
        if self._owns_http:
            self.http.close()

    def __exit__(self, *args):
        self.close()

    def capabilities(self) -> dict:
        return self.registry.capabilities()

    def files_with_urls(self, collection_id: str, item_ids: list[str]) -> dict:
        from .pdf import files_with_urls
        return files_with_urls(self, collection_id, item_ids)

    def download_pdf(self, collection_id: str, item_id: str, *, sha256=None) -> dict:
        from .pdf import download_pdf
        return download_pdf(self, collection_id, item_id, sha256=sha256)

    def read_pdf(self, collection_id: str, item_id: str, **kwargs) -> dict:
        from .pdf import read_pdf
        return read_pdf(self, collection_id, item_id, **kwargs)

    def index_fulltext(self, collection_id: str, **kwargs) -> dict:
        from .pdf import index_fulltext
        return index_fulltext(self, collection_id, **kwargs)

    def search_fulltext(self, collection_id: str, query: str, **kwargs) -> dict:
        from .pdf import search_fulltext
        return search_fulltext(self, collection_id, query, **kwargs)

    def author_statistics(self, collection_id: str, **kwargs) -> dict:
        from .bibliography import author_statistics
        return author_statistics(self, collection_id, **kwargs)

    def export_references(self, collection_id: str, **kwargs) -> dict:
        from .bibliography import export_references
        return export_references(self, collection_id, **kwargs)

    def batch_update_metadata(self, collection_id: str, updates: list[dict], **kwargs) -> dict:
        from .metadata import batch_update_metadata
        return batch_update_metadata(self, collection_id, updates, **kwargs)

    def login(self):
        raise UnverifiedEndpointError(
            "Current password form is SOURCE_CONFIRMED; revised complete login flow is UNVERIFIED. "
            "Use the interactive research helper scripts/login_local.py; no SSO/MFA bypass."
        )

    def check_session(self) -> dict:
        from .auth import session_status

        result = session_status(self.settings.session_file)
        result.update(server_verified=True, collection_count=len(self.list_collections()))
        return result

    def watch_changes(self, collection_id: str, *, duration: float = 30):
        from .realtime import watch_library

        return {
            "mode": "notification_assisted_full_scan",
            "scans": list(watch_library(self, collection_id, duration=duration)),
            "durable_cursor": False,
        }

    def _require(self, name: str):
        self.registry.require(name, research=self._research)

    def _path(self, name: str, ids: dict[str, str]) -> str:
        return self.registry.catalog[name]["path"].format(
            **{key: identifier(value) for key, value in ids.items()}
        )

    def _pause(self):
        delay = self.settings.min_interval - (time.monotonic() - self._last_request)
        if delay > 0:
            time.sleep(delay)
        self._last_request = time.monotonic()

    @staticmethod
    def _retry_after(response: httpx.Response, attempt: int) -> float:
        raw = response.headers.get("Retry-After", "")
        try:
            delay = float(raw)
        except ValueError:
            try:
                delay = (parsedate_to_datetime(raw) - datetime.now(UTC)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                delay = 2**attempt
        return max(0.0, delay)

    def _request(
        self,
        name: str,
        *,
        ids: dict | None = None,
        params: dict | list | None = None,
        body: dict | None = None,
    ) -> dict:
        self._require(name)
        if not list(self.http.cookies.jar):
            raise AuthenticationError("No local session; run scripts/login_local.py")
        entry = self.registry.catalog[name]
        method = entry["method"]
        url = HOSTS[entry["host"]] + self._path(name, ids or {})
        query = list(params.items()) if isinstance(params, dict) else list(params or [])
        query += [
            ("client", "webapp"),
            ("client_id", ""),
            ("client_version", self.settings.client_version),
        ]
        tries = self.settings.retries + 1 if method == "GET" else 1
        for attempt in range(tries):
            self._pause()
            try:
                response = self.http.request(method, url, params=query, json=body)
            except httpx.TransportError:
                if attempt + 1 < tries:
                    time.sleep(min(2**attempt, 5))
                    continue
                raise TransportError(
                    f"{name}: network failure; write requests are never retried"
                ) from None
            self.audit.append(
                {
                    "operation": name,
                    "http_status": response.status_code,
                    "at": datetime.now(UTC).isoformat(),
                }
            )
            if response.status_code in (401, 403):
                raise AuthenticationError(
                    f"{name}: HTTP {response.status_code}; renew login or check access"
                )
            if response.status_code in (429, 500, 502, 503, 504) and attempt + 1 < tries:
                delay = self._retry_after(response, attempt)
                if delay > 60:
                    raise APIError(name, response.status_code)
                time.sleep(delay)
                continue
            if not 200 <= response.status_code < 300:
                raise APIError(name, response.status_code)
            try:
                data = response.json()
            except ValueError:
                raise ProtocolError(f"{name}: expected JSON, possibly an expired session") from None
            if not isinstance(data, dict):
                raise ProtocolError(f"{name}: expected a JSON object")
            if data.get("status") not in (None, "ok", "success") or data.get("error"):
                raise ProtocolError(f"{name}: API returned an unsuccessful envelope")
            key = entry["response_key"]
            if key is not None:
                if key not in data:
                    raise ProtocolError(f"{name}: missing expected response field {key}")
                if key in {"item", "list", "collection", "smartlist"} and not isinstance(
                    data[key], dict
                ):
                    raise ProtocolError(f"{name}: invalid response object {key}")
            return data
        raise TransportError(f"{name}: retries exhausted")

    @staticmethod
    def _rows(data: dict, key: str) -> list[dict]:
        rows = data.get(key)
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ProtocolError(f"Invalid {key} response shape")
        return rows

    @staticmethod
    def _item(data: dict) -> dict:
        try:
            return Item.model_validate(data["item"]).model_dump(exclude_none=True)
        except (ValueError, KeyError, TypeError):
            raise ProtocolError("Invalid item response shape") from None

    def list_collections(self) -> list[dict]:
        return self._rows(self._request("list_collections"), "collections")

    def list_lists(self, collection_id: str) -> list[dict]:
        return self._rows(
            self._request("list_lists", ids={"collection_id": collection_id}), "lists"
        )

    def reader_metadata(self, doi: str) -> dict:
        data = self._request("reader_metadata", params={"doi": normalize_doi(doi)})
        meta = data.get("meta")
        try:
            matches = (
                isinstance(meta, dict)
                and isinstance(meta.get("doi"), str)
                and normalize_doi(meta["doi"]) == normalize_doi(doi)
            )
        except ValueError:
            matches = False
        if not matches:
            raise ProtocolError("Metadata response does not match requested DOI")
        return data

    def get_revisions(self, collection_id: str, item_id: str) -> list[dict]:
        return self._rows(
            self._request(
                "get_revisions", ids={"collection_id": collection_id, "item_id": item_id}
            ),
            "revisions",
        )

    def list_smartlists(self, collection_id: str) -> list[dict]:
        return self._rows(
            self._request("list_smartlists", ids={"collection_id": collection_id}), "smartlists"
        )

    def get_smartlist(self, collection_id: str, smartlist_id: str) -> dict:
        data = self._request(
            "get_smartlist", ids={"collection_id": collection_id, "smartlist_id": smartlist_id}
        )
        if not isinstance(data["smartlist"], dict):
            raise ProtocolError("Invalid smartlist response")
        return data["smartlist"]

    def create_smartlist(self, collection_id: str, name: str, query: str, **kwargs):
        if not name.strip() or not query.strip():
            raise ValueError("Smart List name and query must not be empty")
        return self._write(
            "create_smartlist",
            {"collection_id": collection_id},
            {
                "smartlist": {
                    "id": str(uuid.uuid4()),
                    "collection_id": collection_id,
                    "name": name,
                    "query": query,
                }
            },
            **kwargs,
        )

    def update_smartlist(
        self,
        collection_id: str,
        smartlist_id: str,
        *,
        name: str | None = None,
        query: str | None = None,
        **kwargs,
    ):
        data = {"id": smartlist_id, "collection_id": collection_id}
        for key, value in (("name", name), ("query", query)):
            if value is not None:
                if not value.strip():
                    raise ValueError(f"Smart List {key} must not be empty")
                data[key] = value
        return self._write(
            "update_smartlist",
            {"collection_id": collection_id, "smartlist_id": smartlist_id},
            {"smartlist": data},
            **kwargs,
        )

    def delete_smartlist(self, collection_id: str, smartlist_id: str, **kwargs):
        return self._write(
            "delete_smartlist",
            {"collection_id": collection_id, "smartlist_id": smartlist_id},
            delete_target=smartlist_id,
            **kwargs,
        )

    def set_primary_file(self, collection_id: str, item_id: str, sha256: str, **kwargs):
        if not re.fullmatch(r"[a-fA-F0-9]{64}", sha256):
            raise ValueError("Expected SHA-256")
        return self._write(
            "set_primary_file",
            {"collection_id": collection_id, "item_id": item_id},
            {"hash": sha256.lower()},
            **kwargs,
        )

    def iter_items(
        self,
        collection_id: str,
        *,
        list_id: str | None = None,
        size: int = 50,
        query: str | None = None,
    ):
        if not 1 <= size <= 50:
            raise ValueError("Page size must be between 1 and 50")
        name = "list_list_items" if list_id else "list_items"
        ids = {"collection_id": collection_id}
        if list_id:
            ids["list_id"] = list_id
        cursor = None
        seen_ids: set[str] = set()
        received = 0
        expected = None
        for _ in range(self.settings.max_pages):
            params = {"size": size, "sort[]": "created,asc"}
            if cursor:
                params["scroll_id"] = cursor
            elif query:
                params["query"] = query
            data = self._request(name, ids=ids, params=params)
            rows = self._rows(data, "items")
            if "total" in data:
                total = data["total"]
                if type(total) is not int or total < 0:
                    raise PaginationError("Invalid reported total")
                if expected is not None and total != expected:
                    raise PaginationError("Reported total changed during pagination")
                expected = total
            for row in rows:
                item = self._item({"item": row})
                if item["id"] in seen_ids:
                    raise PaginationError("Duplicate item across pages; snapshot is inconsistent")
                seen_ids.add(item["id"])
                received += 1
                item.setdefault("collection_id", collection_id)
                yield item
            if expected is not None and received >= expected:
                if received > expected:
                    raise PaginationError("Received more items than reported total")
                return
            if not rows:
                if expected is not None and received < expected:
                    raise PaginationError("Pagination ended before reported total")
                return
            cursor = data.get("scroll_id")
            if not cursor:
                if expected is not None and received < expected:
                    raise PaginationError("Missing cursor before reported total")
                return
            if not isinstance(cursor, str):
                raise PaginationError("Invalid scroll cursor")
            # Elasticsearch may reuse a cursor while advancing the result window.
            # Repeated item IDs above and max_pages detect a stuck result stream.
        raise PaginationError("Page limit exceeded; no complete snapshot")

    def list_items(self, collection_id: str, **kwargs) -> list[dict]:
        return list(self.iter_items(collection_id, **kwargs))

    def count_items(self, collection_id: str) -> dict:
        """Read the server's reported total with one verified one-item request."""
        data = self._request(
            "list_items",
            ids={"collection_id": collection_id},
            params={"size": 1, "sort[]": "created,asc"},
        )
        rows = self._rows(data, "items")
        total = data.get("total")
        if type(total) is not int or total < len(rows):
            raise ProtocolError("list_items: missing or invalid total; use a complete scan")
        return {
            "collection_id": collection_id,
            "total": total,
            "source": "live_server_total",
            "as_of": datetime.now(UTC).isoformat(),
            "complete_scan": False,
        }

    def get_item(self, collection_id: str, item_id: str) -> dict:
        return self._item(
            self._request("get_item", ids={"collection_id": collection_id, "item_id": item_id})
        )

    def search(self, query: str, *, field: str = "title", collection_id: str | None = None):
        if field not in ("title", "doi", "pmid") or not query.strip():
            raise ValueError("Nonempty query and field title/doi/pmid required")
        target = normalize_doi(query) if field == "doi" else query.strip().casefold()
        collections = [{"id": collection_id}] if collection_id else self.list_collections()
        results = []
        for collection in collections:
            for item in self.iter_items(collection["id"]):
                if field == "title":
                    matched = target in str(item["article"].get("title", "")).casefold()
                else:
                    value = item["ext_ids"].get(field, "")
                    if field == "doi":
                        try:
                            value = normalize_doi(str(value))
                        except ValueError:
                            continue
                    matched = target == str(value).strip().casefold()
                if matched:
                    results.append(item)
        return results

    def find_by_doi(self, doi: str, collection_id: str | None = None):
        return self.search(doi, field="doi", collection_id=collection_id)

    def cached_search(
        self,
        query: str,
        *,
        field: str = "title",
        collection_id: str | None = None,
        max_age_seconds: int = 300,
        refresh: bool = False,
    ):
        """Legacy raw results from the shared index, with explicit per-result provenance.

        Import deduplication deliberately keeps using the live ``search`` method.
        Use workflow.query_library for bounded compact results and zero-match counts.
        """
        from .workflow import cached_library_items

        if field not in ("title", "doi", "pmid") or not query.strip():
            raise ValueError("Nonempty query and field title/doi/pmid required")
        target = normalize_doi(query) if field == "doi" else query.strip().casefold()
        collections = [{"id": collection_id}] if collection_id else self.list_collections()
        results = []
        for collection in collections:
            items, metadata = cached_library_items(
                self, collection["id"], max_age_seconds=max_age_seconds, refresh=refresh
            )
            for item in items:
                value = (
                    (item.get("article") or {}).get("title", "")
                    if field == "title"
                    else (item.get("ext_ids") or {}).get(field, "")
                )
                if field == "doi":
                    try:
                        value = normalize_doi(str(value))
                    except ValueError:
                        continue
                value = str(value).strip().casefold()
                if (target in value) if field == "title" else (target == value):
                    results.append(item | {"_readcube_cache": metadata})
        return results

    def find_by_title(self, title: str, collection_id: str | None = None):
        return self.search(title, field="title", collection_id=collection_id)

    def find_by_pmid(self, pmid: str, collection_id: str | None = None):
        if not pmid.strip().isdigit():
            raise ValueError("PMID must be numeric")
        return self.search(pmid, field="pmid", collection_id=collection_id)

    def _write(
        self,
        name: str,
        ids: dict,
        body: dict | None = None,
        *,
        authorization: WriteAuthorization | None = None,
        dry_run: bool | None = None,
        delete_target: str | None = None,
    ):
        entry = self.registry.catalog.get(name, {})
        if "method" not in entry:
            raise UnverifiedEndpointError(f"{name}: UNKNOWN; no reviewed contract")
        collection_id = ids["collection_id"]
        is_dry = self.settings.dry_run if dry_run is None else dry_run
        if is_dry:
            return WritePlan(
                operation=name,
                evidence=entry["evidence"],
                verified=self.registry.verified(name),
                collection_id=collection_id,
                method=entry["method"],
                path=self._path(name, ids),
                body=body or {},
            )
        self._check_authorization(collection_id, authorization, delete_target)
        self._require(name)
        from .workflow import (
            invalidate_library_cache,
            library_cache_lock,
            patch_library_cache,
        )

        # Coordinate with scans/other local writers. A lost response may still
        # represent a committed write, so uncertain writes invalidate the index.
        with library_cache_lock(self, collection_id):
            try:
                result = self._request(name, ids=ids, body=body)
            except BaseException:
                invalidate_library_cache(self, collection_id)
                raise
            saved = result.get("item") or {}
            if (
                name == "update_notes"
                and saved.get("id") == ids["item_id"]
                and (saved.get("user_data") or {}).get("notes") == body["notes"]
            ):
                patch_library_cache(
                    self, collection_id, ids["item_id"], user_data_patch={"notes": body["notes"]}
                )
            else:
                invalidate_library_cache(self, collection_id)
            return result

    def _check_authorization(self, collection_id, authorization, delete_target=None):
        if (
            not authorization
            or not authorization.authorized
            or authorization.collection_id != collection_id
            or collection_id not in self.settings.write_collections
        ):
            raise AuthorizationError("Explicit authorization and allowlisted collection required")
        if delete_target and authorization.confirmation != f"DELETE {delete_target}":
            raise AuthorizationError(
                f"Separate deletion confirmation required: DELETE {delete_target}"
            )

    def create_item(self, collection_id: str, metadata: dict, **kwargs):
        return self._write(
            "create_item", {"collection_id": collection_id}, {"item": metadata}, **kwargs
        )

    def import_by_doi(self, collection_id: str, doi: str, **kwargs):
        return self._import_identifier(collection_id, {"doi": normalize_doi(doi)}, **kwargs)

    def import_by_pmid(self, collection_id: str, pmid: str, **kwargs):
        if not pmid.strip().isdigit():
            raise ValueError("PMID must be numeric")
        return self._import_identifier(collection_id, {"pmid": pmid.strip()}, **kwargs)

    def _import_identifier(self, collection_id: str, ext_ids: dict, **kwargs):
        operation = "import_pmid" if "pmid" in ext_ids else "import_identifier"
        is_dry = kwargs.get("dry_run", self.settings.dry_run)
        if is_dry is None:
            is_dry = self.settings.dry_run
        if not is_dry:
            self._check_authorization(collection_id, kwargs.get("authorization"))
            self._require(operation)
            field, value = next(iter(ext_ids.items()))
            recent_id = self._recent_identifiers.get((collection_id, field, value))
            if recent_id:
                recent = self.get_item(collection_id, recent_id)
                stored = recent["ext_ids"].get(field, "")
                if field == "doi" and stored:
                    stored = normalize_doi(stored)
                if str(stored) == value and not recent.get("deleted"):
                    return {"created": False, "needs_review": False, "matches": [recent]}
            matches = self.search(value, field=field, collection_id=collection_id)
            if matches:
                return {"created": False, "needs_review": len(matches) > 1, "matches": matches}
        result = self._write(
            operation,
            {"collection_id": collection_id},
            {"ext_ids": ext_ids, "merge": True, "resolve": True, "resolve_files": False},
            **kwargs,
        )
        if isinstance(result, dict) and isinstance(result.get("item"), dict):
            field, value = next(iter(ext_ids.items()))
            self._recent_identifiers[(collection_id, field, value)] = result["item"]["id"]
            if result.get("merged"):
                return {
                    "created": False,
                    "needs_review": False,
                    "matches": [self._item(result)],
                    "merged": True,
                }
        return result

    def update_metadata(self, collection_id: str, item_id: str, metadata: dict, **kwargs):
        return self._write(
            "update_metadata",
            {"collection_id": collection_id, "item_id": item_id},
            {"item": metadata},
            **kwargs,
        )

    def update_notes(self, collection_id: str, item_id: str, notes: str, **kwargs):
        return self._write(
            "update_notes",
            {"collection_id": collection_id, "item_id": item_id},
            {"notes": notes},
            **kwargs,
        )

    def update_tags(self, collection_id: str, item_id: str, tags: list[str], **kwargs):
        return self._tags("set_tags", collection_id, item_id, tags, **kwargs)

    def add_tags(self, collection_id: str, item_id: str, tags: list[str], **kwargs):
        return self._tags("add_tags", collection_id, item_id, tags, **kwargs)

    def remove_tags(self, collection_id: str, item_id: str, tags: list[str], **kwargs):
        return self._tags("remove_tags", collection_id, item_id, tags, **kwargs)

    def _tags(self, name, collection_id, item_id, tags, **kwargs):
        if not all(isinstance(tag, str) and tag.strip() for tag in tags):
            raise ValueError("Tags must be nonempty strings")
        return self._write(
            name,
            {"collection_id": collection_id, "item_id": item_id},
            {"tags": list(dict.fromkeys(tags))},
            **kwargs,
        )

    def create_list(self, collection_id: str, name: str, parent_id: str | None = None, **kwargs):
        if not name.strip():
            raise ValueError("List name required")
        if parent_id:
            identifier(parent_id)
        return self._write(
            "create_list",
            {"collection_id": collection_id},
            {
                "list": {
                    "id": str(uuid.uuid4()),
                    "collection_id": collection_id,
                    "name": name.strip(),
                    "parent_id": parent_id,
                }
            },
            **kwargs,
        )

    def rename_list(self, collection_id: str, list_id: str, name: str, **kwargs):
        if not name.strip():
            raise ValueError("List name required")
        return self._write(
            "rename_list",
            {"collection_id": collection_id, "list_id": list_id},
            {"list": {"id": list_id, "collection_id": collection_id, "name": name.strip()}},
            **kwargs,
        )

    def move_list(self, collection_id: str, list_id: str, parent_id: str | None, **kwargs):
        """Move an existing List within its library, preserving name and membership."""
        identifier(list_id)
        if parent_id is not None:
            identifier(parent_id)
        if parent_id == list_id:
            raise ValueError("A List cannot be its own parent")
        ids = {"collection_id": collection_id, "list_id": list_id}
        body = {"list": {"id": list_id, "collection_id": collection_id, "parent_id": parent_id}}
        if kwargs.get("dry_run", self.settings.dry_run):
            return self._write("move_list", ids, body, **kwargs)
        self._check_authorization(collection_id, kwargs.get("authorization"), None)
        self._require("move_list")
        rows = {row["id"]: row for row in self.list_lists(collection_id) if not row.get("deleted")}
        if list_id not in rows or (parent_id is not None and parent_id not in rows):
            raise ValueError("List and parent must exist in the selected library")
        visited = {list_id}
        ancestor = parent_id
        while ancestor:
            if ancestor in visited:
                raise ValueError("Moving the List would create a hierarchy cycle")
            if ancestor not in rows:
                raise ProtocolError("Incomplete parent hierarchy")
            visited.add(ancestor)
            ancestor = rows[ancestor].get("parent_id")
        current = rows[list_id]
        if (current.get("parent_id") or None) == parent_id:
            return {"changed": False, "verified": True, "list": current}
        self._write("move_list", ids, body, **kwargs)
        saved = next((row for row in self.list_lists(collection_id) if row["id"] == list_id), None)
        if (
            saved is None
            or saved.get("deleted")
            or (saved.get("parent_id") or None) != parent_id
            or saved.get("name") != current.get("name")
        ):
            raise ProtocolError("List move read-back did not match")
        return {"changed": True, "verified": True, "list": saved}

    def add_to_list(self, collection_id: str, list_id: str, item_id: str, **kwargs):
        identifier(item_id)
        return self._write(
            "add_to_list",
            {"collection_id": collection_id, "list_id": list_id},
            {"item_ids": [item_id]},
            **kwargs,
        )

    def remove_from_list(self, collection_id: str, list_id: str, item_id: str, **kwargs):
        identifier(item_id)
        return self._write(
            "remove_from_list",
            {"collection_id": collection_id, "list_id": list_id},
            {"item_ids": [item_id]},
            **kwargs,
        )

    def delete_item(self, collection_id: str, item_id: str, **kwargs):
        return self._write(
            "delete_item",
            {"collection_id": collection_id, "item_id": item_id},
            delete_target=item_id,
            **kwargs,
        )

    def delete_list(self, collection_id: str, list_id: str, **kwargs):
        return self._write(
            "delete_list",
            {"collection_id": collection_id, "list_id": list_id},
            delete_target=list_id,
            **kwargs,
        )

    def get_annotations(self, collection_id: str, item_id: str):
        return self._rows(
            self._request(
                "get_annotations", ids={"collection_id": collection_id, "item_id": item_id}
            ),
            "annotations",
        )

    def create_annotation(self, collection_id: str, item_id: str, annotation, **kwargs):
        from .annotations import single_annotation_body

        result = self._write(
            "create_annotation",
            {"collection_id": collection_id},
            single_annotation_body(item_id, annotation),
            **kwargs,
        )
        if isinstance(result, WritePlan):
            return result
        rows = result.get("result")
        if (
            not isinstance(rows, list)
            or len(rows) != 1
            or rows[0].get("saved") is not True
            or not isinstance(rows[0].get("object"), dict)
            or rows[0]["object"].get("id") != item_id
        ):
            raise ProtocolError("Annotation create did not confirm the requested item")
        return result

    def update_annotation(
        self, collection_id: str, item_id: str, annotation_id: str, patch: dict, **kwargs
    ):
        return self._write(
            "update_annotation",
            {"collection_id": collection_id, "item_id": item_id, "annotation_id": annotation_id},
            patch,
            **kwargs,
        )

    def delete_annotation(self, collection_id: str, item_id: str, annotation_id: str, **kwargs):
        return self._write(
            "delete_annotation",
            {"collection_id": collection_id, "item_id": item_id, "annotation_id": annotation_id},
            delete_target=annotation_id,
            **kwargs,
        )

    def upload_pdf(
        self,
        collection_id: str,
        item_id: str,
        path: str | Path,
        *,
        authorization: WriteAuthorization | None = None,
        dry_run: bool | None = None,
    ):
        return self._upload_pdf(
            collection_id, item_id, path, authorization=authorization, dry_run=dry_run
        )

    def import_pdf(
        self,
        collection_id: str,
        path: str | Path,
        *,
        authorization: WriteAuthorization | None = None,
        dry_run: bool | None = None,
    ):
        """Import a PDF as a reference using the server's metadata resolution and merge flow."""
        if self.settings.dry_run if dry_run is None else dry_run:
            return self._upload_pdf(
                collection_id, None, path, authorization=authorization, dry_run=True
            )
        self._check_authorization(collection_id, authorization)
        self._require("upload_file")
        self._require("import_pdf_flow")
        path, digest = self._pdf_info(path)
        key = (collection_id, digest)
        cache_path = (
            self.settings.state_dir / self.session / f"pdf-imports-{identifier(collection_id)}.json"
        )
        try:
            saved = json.loads(cache_path.read_text()) if cache_path.exists() else {}
            if not isinstance(saved, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in saved.items()
            ):
                raise ValueError
        except (ValueError, OSError):
            raise ProtocolError(
                "Invalid local PDF import cache; inspect local state before retrying"
            ) from None
        recent = self._recent_pdf_imports.get(key) or saved.get(digest)
        rows = []
        if recent:
            try:
                rows = [self.get_item(collection_id, recent)]
            except APIError as error:
                if error.status != 404:
                    raise
        matches = [
            item
            for item in rows
            if not item.get("deleted")
            and digest
            in {
                item.get("primary_file_hash"),
                *(file.get("sha256") or file.get("hash") for file in item.get("files", [])),
            }
        ]
        if not matches:
            matches = [
                item
                for item in self.iter_items(collection_id)
                if not item.get("deleted")
                and digest
                in {
                    item.get("primary_file_hash"),
                    *(file.get("sha256") or file.get("hash") for file in item.get("files", [])),
                }
            ]
        if matches:
            result = {
                "created": False,
                "needs_review": len(matches) > 1,
                "matches": matches,
                "sha256": digest,
                "associated": True,
            }
            if len(matches) == 1:
                result["item"] = matches[0]
                self._recent_pdf_imports[key] = matches[0]["id"]
                saved[digest] = matches[0]["id"]
                private_json_write(cache_path, saved)
            return result
        result = self._upload_pdf(
            collection_id, None, path, authorization=authorization, dry_run=dry_run
        )
        self._recent_pdf_imports[key] = result["item"]["id"]
        saved[digest] = result["item"]["id"]
        private_json_write(cache_path, saved)
        result.update(created=True, needs_review=False)
        return result

    def _pdf_info(self, path):
        path = Path(path).resolve(strict=True)
        if self.settings.upload_roots and not any(
            path.is_relative_to(root.resolve()) for root in self.settings.upload_roots
        ):
            raise AuthorizationError("PDF is outside configured upload roots")
        digest = hashlib.sha256()
        with path.open("rb") as file:
            header = file.read(16384)
            if not header.startswith(b"%PDF-") or b"MicrosoftIRMServices Protected PDF" in header:
                raise ValueError("Expected an unprotected PDF file")
            digest.update(header)
            while block := file.read(1024 * 1024):
                digest.update(block)
        return path, digest.hexdigest()

    def _upload_pdf(self, collection_id, item_id, path, *, authorization, dry_run):
        path, digest = self._pdf_info(path)
        body = {
            "file_name": path.name,
            "file_size": path.stat().st_size,
            "primary": False,
            "hash": digest,
            "resolve": False,
            "skip_resolve": True,
            "merge": False,
        }
        ids = {"collection_id": collection_id, "item_id": item_id}
        operation = "add_file" if item_id else "upload_file"
        flow = "upload_pdf_flow" if item_id else "import_pdf_flow"
        if not item_id:
            ids = {"collection_id": collection_id}
            body.pop("primary")
            body.update(resolve=True, skip_resolve=False, merge=True, user_data={"tags": []})
        is_dry = self.settings.dry_run if dry_run is None else dry_run
        if not is_dry:
            self._require(operation)
            self._require("uploads_pending")
            if not self._research and not self.registry.verified(flow):
                raise UnverifiedEndpointError(f"{flow}: UNVERIFIED; storage PUT must also pass")
        first = self._write(operation, ids, body, authorization=authorization, dry_run=dry_run)
        if isinstance(first, WritePlan):
            first.note = f"Plan: {operation} -> isolated storage PUT -> uploads_pending -> {operation} -> get_item."
            return first
        if first.get("item"):
            if not isinstance(first["item"], dict) or not isinstance(first["item"].get("id"), str):
                raise ProtocolError("Upload initialization returned an invalid item")
            return self._verify_attachment(
                collection_id, item_id or first["item"]["id"], body["hash"], flow
            )
        upload_id = first.get("upload_id")
        url = first.get("upload_url")
        if not upload_id or not isinstance(url, str):
            raise ProtocolError("Upload initialization missing upload_id/upload_url")
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in self.settings.upload_hosts
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            raise AuthorizationError("Upload destination requires an explicit hostname allowlist")
        # A fresh client prevents ReadCube session cookies from leaking to a signed storage URL.
        try:
            cookies = (
                self.http.cookies
                if parsed.hostname in {"sync.readcube.com", "services.readcube.com"}
                else None
            )
            with httpx.Client(
                timeout=self.settings.upload_timeout, follow_redirects=False, cookies=cookies
            ) as storage:
                with path.open("rb") as file:
                    response = storage.put(
                        url,
                        content=file,
                        headers={"Content-Type": "application/pdf", "Accept": "application/json"},
                    )
                if response.status_code != 200:
                    raise APIError("storage_put", response.status_code)
        except httpx.TransportError:
            raise TransportError(
                "Storage PUT failed; do not automatically retry the write"
            ) from None
        deadline = time.monotonic() + self.settings.upload_timeout
        while time.monotonic() < deadline:
            pending = self._request("uploads_pending", ids={"collection_id": collection_id})
            uploads = pending.get("uploads", pending)
            row = uploads.get(str(upload_id)) if isinstance(uploads, dict) else None
            if row is not None and not isinstance(row, dict):
                raise ProtocolError("Upload pending response has an invalid entry")
            if row and row.get("status") == "failed":
                raise ProtocolError("Server-side upload processing failed")
            if row and row.get("status") == "completed":
                if row.get("hash") != body["hash"]:
                    raise ProtocolError("Processed PDF hash does not match local SHA-256")
                linked = self._write(
                    operation, ids, body, authorization=authorization, dry_run=False
                )
                if not isinstance(linked.get("item"), dict):
                    raise ProtocolError("Upload association returned an invalid item")
                target = item_id or linked.get("item", {}).get("id")
                if not target:
                    raise ProtocolError("Upload association did not return an item ID")
                return self._verify_attachment(collection_id, target, body["hash"], flow)
            time.sleep(3)
        raise UploadPendingError("PDF processing is pending; inspect state before retrying")

    def _verify_attachment(self, collection_id, item_id, digest, flow="upload_pdf_flow"):
        item = self.get_item(collection_id, item_id)
        hashes = {file.get("sha256") or file.get("hash") for file in item.get("files", [])}
        hashes.add(item.get("primary_file_hash"))
        if digest not in hashes:
            raise ProtocolError("PDF association not confirmed by server readback")
        self.audit.append(
            {
                "operation": flow,
                "http_status": 200,
                "at": datetime.now(UTC).isoformat(),
            }
        )
        return {"item": item, "sha256": digest, "associated": True}

    def sync_changes(self, collection_id: str) -> SyncDelta:
        from .workflow import cached_library_items

        identifier(collection_id)
        path = self.settings.state_dir / self.session / f"{collection_id}.json"
        previous = json.loads(path.read_text()) if path.exists() else {}
        # Never replace the previous snapshot when a page fails or cursor loops.
        current = {
            item["id"]: hashlib.sha256(
                json.dumps(item, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            for item in cached_library_items(self, collection_id, refresh=True)[0]
        }
        delta = SyncDelta(
            added=sorted(current.keys() - previous.keys()),
            changed=sorted(
                key for key in current.keys() & previous.keys() if current[key] != previous[key]
            ),
            missing=sorted(previous.keys() - current.keys()),
            total=len(current),
        )
        private_json_write(path, current)
        return delta
