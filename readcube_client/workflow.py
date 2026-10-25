"""Compact cached library queries and verified note appends using reviewed API operations."""

import copy
import hashlib
import heapq
import json
import os
import tempfile
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from weakref import WeakValueDictionary

from .errors import ProtocolError
from .models import WriteAuthorization

_CACHE_VERSION = 2
_NOTE_PREVIEW_LENGTH = 320
_LOCKS = WeakValueDictionary()
_LOCKS_GUARD = threading.Lock()
_HELD_LOCKS = threading.local()


def _atomic_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".index-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, separators=(",", ":"))
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _cache_path(client, collection_id):
    from .client import identifier

    identifier(collection_id)
    key = hashlib.sha256(f"{client.session}:{collection_id}".encode()).hexdigest()
    return client.settings.state_dir / "library-index" / f"{key}.json"


@contextmanager
def _state_lock(client, collection_id, suffix):
    """Hold a reentrant thread and process lock for one state resource."""
    path = _cache_path(client, collection_id).with_suffix(suffix).resolve()
    key = str(path)
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(key, threading.RLock())
    with lock:
        held = getattr(_HELD_LOCKS, "paths", None)
        if held is None:
            held = _HELD_LOCKS.paths = set()
        if key in held:
            yield
            return
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if os.name == "nt":
                import msvcrt

                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b"0")
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX)
            held.add(key)
            try:
                yield
            finally:
                held.remove(key)
        finally:
            # Closing the descriptor releases the operating-system lock, including on errors.
            os.close(descriptor)


@contextmanager
def library_cache_lock(client, collection_id):
    """Serialize cache commits and short writes, never the network work of a full scan."""
    with _state_lock(client, collection_id, ".lock"):
        yield


def _generation(client, collection_id):
    path = _cache_path(client, collection_id).with_suffix(".generation")
    try:
        return int(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return 0
    except ValueError:
        raise ProtocolError("Invalid local library cache generation") from None


def _bump_generation(client, collection_id):
    path = _cache_path(client, collection_id).with_suffix(".generation")
    _atomic_json(path, _generation(client, collection_id) + 1)


def _memory_cache(client):
    cache = getattr(client, "_workflow_index_cache", None)
    if cache is None:
        cache = client._workflow_index_cache = OrderedDict()
    return cache


def _file_signature(path):
    stat = path.stat()
    return stat.st_ino, stat.st_mtime_ns, stat.st_size


def _remember(client, path, snapshot):
    cache = _memory_cache(client)
    cache[path] = (_file_signature(path), snapshot)
    cache.move_to_end(path)
    while len(cache) > 8:
        cache.popitem(last=False)


def _load_snapshot(client, collection_id):
    path = _cache_path(client, collection_id)
    try:
        signature = _file_signature(path)
        remembered = _memory_cache(client).get(path)
        saved = (
            remembered[1]
            if remembered and remembered[0] == signature
            else json.loads(path.read_text(encoding="utf-8"))
        )
        if (
            not isinstance(saved, dict)
            or saved.get("version") != _CACHE_VERSION
            or saved.get("collection_id") != collection_id
            or saved.get("complete") is not True
            or saved.get("contract_sha256") != client.registry.signature("list_items")
            or not isinstance(saved.get("fetched_at"), (int, float))
            or not isinstance(saved.get("raw_items"), list)
            or not isinstance(saved.get("items"), list)
            or len(saved["raw_items"]) != len(saved["items"])
        ):
            return None
        if not remembered or remembered[0] != signature:
            if not all(
                isinstance(item, dict) and isinstance(item.get("id"), str)
                for item in saved["raw_items"] + saved["items"]
            ):
                return None
            _remember(client, path, saved)
        return saved
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _save_snapshot(client, collection_id, snapshot):
    path = _cache_path(client, collection_id)
    _atomic_json(path, snapshot)
    _remember(client, path, snapshot)


def invalidate_library_cache(client, collection_id):
    """Discard this session's full snapshot after an uncertain or unrepresented mutation."""
    with library_cache_lock(client, collection_id):
        _bump_generation(client, collection_id)
        path = _cache_path(client, collection_id)
        _memory_cache(client).pop(path, None)
        path.unlink(missing_ok=True)


def _compact(item):
    article, user = item.get("article") or {}, item.get("user_data") or {}
    ext_ids = item.get("ext_ids") or {}
    return {
        "id": item["id"],
        "title": article.get("title", ""),
        "year": article.get("year"),
        "journal": article.get("journal"),
        "doi": ext_ids.get("doi"),
        "pmid": ext_ids.get("pmid"),
        "notes": user.get("notes") or "",
        "tags": user.get("tags") or [],
        "unread": user.get("unread"),
        "last_read": user.get("last_read"),
        "has_annotations": bool(user.get("has_annotations")),
    }


def _replace_snapshot_item(snapshot, item):
    item_id = item.get("id")
    for index, previous in enumerate(snapshot["raw_items"]):
        if previous["id"] == item_id:
            updated = copy.deepcopy(snapshot)
            if item.get("deleted"):
                del updated["raw_items"][index]
                del updated["items"][index]
            else:
                updated["raw_items"][index] = copy.deepcopy(item)
                updated["items"][index] = _compact(item)
            return updated
    return None


def update_library_cache(client, collection_id, item):
    """Replace a known item after a fresh read; never extend the full-scan freshness window."""
    with library_cache_lock(client, collection_id):
        _bump_generation(client, collection_id)
        snapshot = _load_snapshot(client, collection_id)
        if snapshot is None:
            return
        updated = _replace_snapshot_item(snapshot, item)
        if updated is not None:
            _save_snapshot(client, collection_id, updated)
        else:
            # An unknown item means the complete snapshot no longer describes this library.
            invalidate_library_cache(client, collection_id)


def patch_library_cache(client, collection_id, item_id, *, user_data_patch):
    """Patch a known successful mutation while preserving unrelated raw/compact fields."""
    with library_cache_lock(client, collection_id):
        snapshot = _load_snapshot(client, collection_id)
        if snapshot is None:
            _bump_generation(client, collection_id)
            return
        for previous in snapshot["raw_items"]:
            if previous["id"] == item_id:
                item = copy.deepcopy(previous)
                item["user_data"] = (item.get("user_data") or {}) | user_data_patch
                update_library_cache(client, collection_id, item)
                return
        invalidate_library_cache(client, collection_id)


def _cached_snapshot(client, collection_id, *, max_age_seconds=300, refresh=False):
    if not 0 <= max_age_seconds <= 3600:
        raise ValueError("Invalid cache age")
    client.registry.require("list_items")

    def fresh_snapshot():
        saved = _load_snapshot(client, collection_id) if not refresh and max_age_seconds else None
        if saved is not None and 0 <= time.time() - saved["fetched_at"] < max_age_seconds:
            return saved
        return None

    with library_cache_lock(client, collection_id):
        snapshot = fresh_snapshot()
        if snapshot is not None:
            return snapshot, "cache"
    # A dedicated scan lock coalesces cold readers without delaying notes behind a full scan.
    with _state_lock(client, collection_id, ".scan.lock"):
        for attempt in range(2):
            with library_cache_lock(client, collection_id):
                snapshot = fresh_snapshot()
                if snapshot is not None:
                    return snapshot, "cache"
                generation = _generation(client, collection_id)
            raw_items = [i for i in client.list_items(collection_id) if not i.get("deleted")]
            snapshot = {
                "version": _CACHE_VERSION,
                "collection_id": collection_id,
                "contract_sha256": client.registry.signature("list_items"),
                "complete": True,
                "fetched_at": time.time(),
                "raw_items": raw_items,
                "items": [_compact(i) for i in raw_items],
            }
            with library_cache_lock(client, collection_id):
                if generation != _generation(client, collection_id):
                    # Never overwrite a newer note with a scan started before that write.
                    if attempt == 0:
                        continue
                    raise ProtocolError("Library changed during both scans; retry the query")
                _save_snapshot(client, collection_id, snapshot)
                return snapshot, "live_full_scan"


def _metadata(snapshot, source):
    return {
        "collection_id": snapshot["collection_id"],
        "source": source,
        "as_of": datetime.fromtimestamp(snapshot["fetched_at"], UTC).isoformat(),
        "age_seconds": round(max(0.0, time.time() - snapshot["fetched_at"]), 3),
        "complete_scan": True,
        "total": len(snapshot["raw_items"]),
    }


def cached_library_items(client, collection_id, *, max_age_seconds=300, refresh=False):
    """Return detached complete raw items and explicit freshness metadata for cached search."""
    snapshot, source = _cached_snapshot(
        client, collection_id, max_age_seconds=max_age_seconds, refresh=refresh
    )
    return copy.deepcopy(snapshot["raw_items"]), _metadata(snapshot, source)


def _read_sort_key(item):
    value = item.get("last_read")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).timestamp()
        except ValueError:
            pass
    return 0.0


def _preview(item):
    result = copy.deepcopy(item)
    notes = str(result["notes"])
    result["notes"] = notes[:_NOTE_PREVIEW_LENGTH]
    result["notes_truncated"] = len(notes) > _NOTE_PREVIEW_LENGTH
    return result


def query_library(
    client,
    collection_id,
    *,
    query="",
    field="title",
    read_only=False,
    annotated_only=False,
    limit=20,
    max_age_seconds=300,
    refresh=False,
):
    """A complete scan on cache miss, then bounded local queries; never label cache as live."""
    if field not in ("title", "doi", "pmid", "notes", "tags"):
        raise ValueError("Unsupported query field")
    if not 1 <= limit <= 100:
        raise ValueError("Invalid limit")
    target = query.strip().casefold()
    if field == "doi":
        from .client import normalize_doi

        target = normalize_doi(query) if target else ""
    snapshot, source = _cached_snapshot(
        client, collection_id, max_age_seconds=max_age_seconds, refresh=refresh
    )
    items = snapshot["items"]
    matches = []
    for item in items:
        if read_only and item.get("unread") is not False:
            continue
        if annotated_only and not item.get("has_annotations"):
            continue
        value = item.get(field) or ""
        if field == "tags":
            value = " ".join(str(tag) for tag in value)
        value = str(value).strip().casefold()
        if field == "doi" and value:
            try:
                value = normalize_doi(value)
            except ValueError:
                continue
        if target and not (value == target if field in ("doi", "pmid") else target in value):
            continue
        matches.append(item)
    return _metadata(snapshot, source) | {
        "marked_read": sum(i.get("unread") is False for i in items),
        "annotated": sum(bool(i.get("has_annotations")) for i in items),
        "matched": len(matches),
        "truncated": len(matches) > limit,
        "items": [_preview(i) for i in heapq.nlargest(limit, matches, key=_read_sort_key)],
        "reading_status_basis": "unread=false is a ReadCube mark, not proof of full reading",
    }


def workflow_status(client, collection_id=None):
    """Inspect effective runtime permissions and verification without remote requests."""
    return {
        "collection_id": collection_id,
        "write_allowed": collection_id in client.settings.write_collections
        if collection_id
        else None,
        "write_collections": list(client.settings.write_collections),
        "operations": {
            op: {"verified": client.registry.verified(op)}
            for op in ("list_items", "get_item", "update_notes")
        },
        "default_dry_run": client.settings.dry_run,
    }


def append_note(client, collection_id, item_id, text, *, authorized=False, dry_run=True):
    """Preserve existing notes; serialize local appends, append once, and verify saved text."""
    from .client import identifier

    identifier(item_id)
    if not text.strip():
        raise ValueError("Note text must not be empty")
    authorization = WriteAuthorization(collection_id=collection_id, authorized=authorized)
    if not dry_run:
        client._check_authorization(collection_id, authorization)
    client.registry.require("get_item")
    client.registry.require("update_notes")
    with library_cache_lock(client, collection_id):
        item = client.get_item(collection_id, item_id)
        previous = (item.get("user_data") or {}).get("notes") or ""
        present = previous == text or ("\n" + text + "\n") in ("\n" + previous + "\n")
        notes = (
            previous
            if present
            else previous + ("\n" if previous and not previous.endswith("\n") else "") + text
        )
        result = {
            "collection_id": collection_id,
            "item_id": item_id,
            "title": (item.get("article") or {}).get("title"),
            "dry_run": dry_run,
            "write_allowed": collection_id in client.settings.write_collections,
            "already_present": present,
            "verified": False,
        }
        if dry_run:
            plan = client.update_notes(collection_id, item_id, notes, dry_run=True)
            return result | {"plan": plan.model_dump(mode="json")}
        if present:
            update_library_cache(client, collection_id, item)
            return result | {"changed": False, "verified": True}
        prior_snapshot = _load_snapshot(client, collection_id)
        try:
            client.update_notes(
                collection_id, item_id, notes, authorization=authorization, dry_run=False
            )
            check = client.get_item(collection_id, item_id)
            if (check.get("user_data") or {}).get("notes") != notes:
                raise ProtocolError(
                    "Note write returned, but read-back did not match; inspect before retrying"
                )
            if _load_snapshot(client, collection_id) is None and prior_snapshot is not None:
                # Minimal write envelopes invalidate the cache until this exact read-back.
                # The library lock excludes other local writes, so the old snapshot can be
                # restored with only this verified item replaced and its original age kept.
                restored = _replace_snapshot_item(prior_snapshot, check)
                if restored is not None:
                    _bump_generation(client, collection_id)
                    _save_snapshot(client, collection_id, restored)
            else:
                update_library_cache(client, collection_id, check)
        except Exception:
            # A lost response or failed read-back can still mean the write committed remotely.
            invalidate_library_cache(client, collection_id)
            raise
        return result | {"changed": True, "verified": True}
