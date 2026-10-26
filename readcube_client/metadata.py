"""Bounded metadata patches with preflight validation, durable backups and read-back."""

import copy
import uuid
from datetime import UTC, datetime

from .auth import private_json_write
from .client import identifier, normalize_doi
from .errors import ProtocolError, ReadCubeError
from .models import WriteAuthorization
from .workflow import _state_lock

ARTICLE_FIELDS = {
    "title",
    "authors",
    "year",
    "journal",
    "volume",
    "issue",
    "pages",
    "abstract",
    "url",
    "publisher",
    "issn",
    "isbn",
    "type",
    "date",
}
IDENTIFIERS = {"doi", "pmid", "arxiv", "isbn"}


def validate_patch(patch):
    if not isinstance(patch, dict) or not patch or set(patch) - {"article", "ext_ids"}:
        raise ValueError("Only article and ext_ids metadata may be patched")
    patch = copy.deepcopy(patch)
    for key, allowed in [("article", ARTICLE_FIELDS), ("ext_ids", IDENTIFIERS)]:
        if key not in patch:
            continue
        fields = patch[key]
        if not isinstance(fields, dict) or not fields or set(fields) - allowed:
            raise ValueError("Unsupported or empty metadata fields")
        for field, value in fields.items():
            if field == "authors":
                if (
                    not isinstance(value, list)
                    or len(value) > 500
                    or any(not isinstance(v, (str, dict)) for v in value)
                ):
                    raise ValueError("Invalid authors")
                from .authors import author_names

                author_names({"authors": value})
            elif value is not None and not isinstance(value, (str, int)):
                raise ValueError("Metadata values must be text, year or null")
            if isinstance(value, str) and len(value) > 100000:
                raise ValueError("Metadata field too large")
        if key == "ext_ids" and fields.get("doi"):
            fields["doi"] = normalize_doi(fields["doi"])
    return patch


def batch_update_metadata(
    client, collection_id, updates, *, authorized=False, dry_run=True, stop_on_error=True
):
    identifier(collection_id)
    if not 1 <= len(updates) <= 100:
        raise ValueError("Update between 1 and 100 records per call")
    parsed = []
    for update in updates:
        if (
            not isinstance(update, dict)
            or set(update) - {"item_id", "patch"}
            or not {"item_id", "patch"} <= set(update)
        ):
            raise ValueError("Provide item_id and patch only")
        iid = identifier(update["item_id"])
        parsed.append((iid, validate_patch(update["patch"])))
    if len({i for i, _ in parsed}) != len(parsed):
        raise ValueError("Duplicate item IDs in batch")
    if dry_run:
        return {
            "dry_run": True,
            "updates": [{"item_id": i, "patch": p} for i, p in parsed],
            "verified": client.registry.verified("update_metadata"),
            "note": "Execution merges these fields with a fresh record and verifies each write.",
        }
    auth = WriteAuthorization(collection_id=collection_id, authorized=authorized)
    client._check_authorization(collection_id, auth)
    client._require("get_item")
    client._require("update_metadata")
    collections = client.list_collections()
    own = next((c for c in collections if c.get("id") == collection_id), None)
    if own is None or not own.get("user", {}).get("can_manage_item"):
        raise ValueError("This library does not permit metadata updates")
    identifier("metadata")
    journal = {"at": datetime.now(UTC).isoformat(), "collection_id": collection_id, "results": []}
    path = client.settings.state_dir / "metadata-journals" / (uuid.uuid4().hex + ".json")
    # Read and validate all targets before the first write; no implicit whole-library scan.
    # Serialize metadata batches without holding the shared query/note cache lock
    # across every network read in a potentially large batch. Each actual PATCH
    # still uses the SDK's short cache/write lock and invalidation protocol.
    with _state_lock(client, collection_id, ".metadata-batch.lock"):
        originals = {iid: client.get_item(collection_id, iid) for iid, _ in parsed}
        journal["before"] = originals
        private_json_write(path, journal)
        for index, (iid, patch) in enumerate(parsed):
            merged = {key: copy.deepcopy(originals[iid].get(key) or {}) for key in patch}
            for key, values in patch.items():
                merged[key].update(values)
            try:
                # Preview the concrete merged body before sending it.
                client.update_metadata(collection_id, iid, merged, dry_run=True)
                client.update_metadata(
                    collection_id, iid, merged, authorization=auth, dry_run=False
                )
                saved = client.get_item(collection_id, iid)
                if any(
                    (saved.get(key) or {}).get(k) != v
                    for key, values in patch.items()
                    for k, v in values.items()
                ):
                    raise ProtocolError("Metadata read-back mismatch")
                # ReadCube updates its audit timestamp when metadata changes.
                # Preserve every content field, but do not mistake this timestamp
                # for a lost note, tag, flag, attachment or List membership.
                old_user = originals[iid].get("user_data") or {}
                new_user = saved.get("user_data") or {}
                if {k: v for k, v in old_user.items() if k != "modified"} != {
                    k: v for k, v in new_user.items() if k != "modified"
                }:
                    raise ProtocolError("Unrelated user content changed during metadata update")
                for key in ("files", "list_ids"):
                    if saved.get(key) != originals[iid].get(key):
                        raise ProtocolError(
                            "Unrelated record fields changed during metadata update"
                        )
                journal["results"].append({"item_id": iid, "status": "verified"})
            except (ReadCubeError, ValueError, OSError):
                journal["results"].append(
                    {
                        "item_id": iid,
                        "status": "needs_reconciliation",
                        "error": "Write or read-back failed; inspect current state before retrying.",
                    }
                )
                if stop_on_error:
                    journal["results"] += [
                        {"item_id": i, "status": "not_attempted"} for i, _ in parsed[index + 1 :]
                    ]
                    private_json_write(path, journal)
                    break
            private_json_write(path, journal)
    return {
        "dry_run": False,
        "results": journal["results"],
        "journal_path": str(path),
        "verified": all(r["status"] == "verified" for r in journal["results"]),
        "automatic_write_retries": False,
    }
