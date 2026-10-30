"""Bounded DOI imports using one fresh library scan and durable reconciliation state."""

import json
from types import SimpleNamespace

from .auth import private_json_write
from .client import identifier, normalize_doi
from .errors import APIError, ProtocolError, ReadCubeError
from .models import WriteAuthorization
from .workflow import _generation, _state_lock, library_cache_lock


def _journal_path(client, collection_id):
    return client.settings.state_dir / "batch-imports" / f"{identifier(collection_id)}.json"


def _load_journal(path):
    if path.is_symlink():
        raise ProtocolError("Import journal cannot be a symlink")
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise ProtocolError("Invalid import journal; reconcile before retrying") from None
    if (
        not isinstance(value, dict)
        or value.get("version") != 1
        or not isinstance(value.get("records"), dict)
    ):
        raise ProtocolError("Invalid import journal; reconcile before retrying")
    return value["records"]


def _doi(item):
    try:
        return normalize_doi(str((item.get("ext_ids") or {}).get("doi") or ""))
    except ValueError:
        return None


def batch_import_dois(client, collection_id, dois, *, list_id=None, authorized=False, dry_run=True):
    """Import DOI records sequentially after one complete fresh scan; optionally file them.

    Pending writes are journaled before transmission. A later call never blindly
    retries uncertain imports or List writes; it first verifies known IDs/membership.
    External clients can still write concurrently; the upstream API has no verified
    transaction or unique-key constraint.
    """
    identifier(collection_id)
    if list_id is not None:
        identifier(list_id)
    if not isinstance(dois, list) or not 1 <= len(dois) <= 200:
        raise ValueError("Provide between 1 and 200 DOI strings")
    if any(not isinstance(x, str) for x in dois):
        raise ValueError("Every DOI must be text")
    normalized = [normalize_doi(x) for x in dois]
    unique = list(dict.fromkeys(normalized))
    auth = WriteAuthorization(collection_id=collection_id, authorized=authorized)
    if not dry_run:
        client._check_authorization(collection_id, auth)
        client._require("import_identifier")
        client._require("get_item")
        if list_id:
            client._require("add_to_list")
    client._require("list_items")
    if list_id:
        client._require("list_lists")
        client._require("list_list_items")
    path = _journal_path(client, collection_id)
    lock_client = SimpleNamespace(settings=client.settings, session="doi-batch-lock-v1")
    with _state_lock(lock_client, collection_id, ".batch-import.lock"):
        records = _load_journal(path)
        for doi in unique:
            entry = records.get(doi, {})
            if not isinstance(entry, dict) or entry.get("state") not in (
                None,
                "pending",
                "verified",
            ):
                raise ProtocolError("Invalid import journal entry; reconcile before retrying")
            if entry.get("item_id") is not None:
                try:
                    identifier(entry["item_id"])
                except (ValueError, TypeError):
                    raise ProtocolError(
                        "Invalid import journal item ID; reconcile before retrying"
                    ) from None
            membership = entry.get("membership", {})
            if not isinstance(membership, dict) or any(
                value not in ("pending", "verified") for value in membership.values()
            ):
                raise ProtocolError("Invalid membership journal; reconcile before retrying")
        if list_id and not any(
            row.get("id") == list_id and not row.get("deleted")
            for row in client.list_lists(collection_id)
        ):
            raise ValueError("The destination List does not exist in this library")
        with library_cache_lock(client, collection_id):
            generation = _generation(client, collection_id)
        items = client.list_items(collection_id)
        members = (
            {x["id"] for x in client.list_items(collection_id, list_id=list_id)}
            if list_id
            else set()
        )
        with library_cache_lock(client, collection_id):
            if _generation(client, collection_id) != generation:
                raise ProtocolError("Library changed during preflight; no batch writes were made")
        by_doi = {}
        for row in items:
            key = _doi(row)
            if key and not row.get("deleted"):
                by_doi.setdefault(key, []).append(row["id"])
        results = []
        pending_membership = set()
        stop = False

        def save():
            private_json_write(path, {"version": 1, "records": records})

        for doi in unique:
            if stop:
                results.append({"doi": doi, "status": "not_attempted"})
                continue
            previous = records.get(doi, {})
            if not isinstance(previous, dict) or previous.get("state") not in (
                None,
                "pending",
                "verified",
            ):
                raise ProtocolError("Invalid import journal entry; reconcile before retrying")
            matches = list(dict.fromkeys(by_doi.get(doi, [])))
            known = previous.get("item_id") or client._recent_identifiers.get(
                (collection_id, "doi", doi)
            )
            known_row = None
            if known and known not in matches:
                try:
                    candidate = client.get_item(collection_id, identifier(known))
                except APIError as error:
                    if error.status != 404:
                        results.append(
                            {"doi": doi, "status": "needs_reconciliation", "item_id": known}
                        )
                        stop = True
                        continue
                except ReadCubeError:
                    results.append({"doi": doi, "status": "needs_reconciliation", "item_id": known})
                    stop = True
                    continue
                else:
                    if not candidate.get("deleted") and _doi(candidate) == doi:
                        matches.append(known)
                        known_row = candidate
            if len(matches) > 1:
                results.append({"doi": doi, "status": "needs_review", "matches": matches})
                continue
            if (
                (previous.get("state") == "pending" and not previous.get("item_id"))
                or (known and known not in matches)
                or (previous.get("state") == "verified" and not matches)
            ):
                results.append({"doi": doi, "status": "needs_reconciliation", "matches": matches})
                stop = True
                continue
            if dry_run:
                results.append(
                    {
                        "doi": doi,
                        "status": "existing" if matches else "would_import",
                        "item_id": matches[0] if matches else None,
                        "in_list": matches[0] in members if list_id and matches else None,
                    }
                )
                continue
            item_id = matches[0] if matches else None
            if item_id:
                try:
                    current = (
                        known_row
                        if known_row is not None
                        else client.get_item(collection_id, item_id)
                    )
                except ReadCubeError:
                    results.append(
                        {"doi": doi, "status": "needs_reconciliation", "item_id": item_id}
                    )
                    stop = True
                    continue
                if current.get("deleted") or _doi(current) != doi:
                    results.append({"doi": doi, "status": "needs_reconciliation"})
                    stop = True
                    continue
                status = "existing"
                records[doi] = previous | {"state": "verified", "item_id": item_id}
                save()
            else:
                records[doi] = {"state": "pending"}
                save()
                try:
                    with library_cache_lock(client, collection_id):
                        if _generation(client, collection_id) != generation:
                            records.pop(doi)
                            save()
                            raise ProtocolError(
                                "Library changed during batch; resume after a fresh scan"
                            )
                        response = client._write(
                            "import_identifier",
                            {"collection_id": collection_id},
                            {
                                "ext_ids": {"doi": doi},
                                "merge": True,
                                "resolve": True,
                                "resolve_files": False,
                            },
                            authorization=auth,
                            dry_run=False,
                        )
                        generation = _generation(client, collection_id)
                    item_id = identifier((response.get("item") or {}).get("id", ""))
                    records[doi]["item_id"] = item_id
                    save()
                    current = client.get_item(collection_id, item_id)
                    if current.get("deleted") or _doi(current) != doi:
                        raise ProtocolError("Imported DOI was not confirmed by readback")
                    records[doi]["state"] = "verified"
                    save()
                    by_doi[doi] = [item_id]
                    client._recent_identifiers[(collection_id, "doi", doi)] = item_id
                    status = "merged" if response.get("merged") else "imported"
                except (ReadCubeError, ValueError, OSError):
                    results.append(
                        {
                            "doi": doi,
                            "status": "needs_reconciliation",
                            "item_id": records.get(doi, {}).get("item_id"),
                        }
                    )
                    stop = True
                    continue
            result = {"doi": doi, "status": status, "item_id": item_id, "verified": True}
            if list_id:
                membership = records[doi].setdefault("membership", {})
                if not isinstance(membership, dict):
                    raise ProtocolError("Invalid membership journal; reconcile before retrying")
                if item_id in members:
                    membership[list_id] = "verified"
                    save()
                    result["list_verified"] = True
                elif item_id in pending_membership:
                    membership[list_id] = "pending"
                    save()
                    result["list_verified"] = False
                elif membership.get(list_id) == "pending":
                    result["list_status"] = "needs_reconciliation"
                    stop = True
                else:
                    membership[list_id] = "pending"
                    save()
                    try:
                        with library_cache_lock(client, collection_id):
                            if _generation(client, collection_id) != generation:
                                membership.pop(list_id)
                                save()
                                raise ProtocolError(
                                    "Library changed during batch; resume after a fresh scan"
                                )
                            client.add_to_list(
                                collection_id, list_id, item_id, authorization=auth, dry_run=False
                            )
                            generation = _generation(client, collection_id)
                        pending_membership.add(item_id)
                        result["list_verified"] = False
                    except (ReadCubeError, ValueError, OSError):
                        result["list_status"] = "needs_reconciliation"
                        stop = True
            results.append(result)
        if list_id and pending_membership:
            try:
                confirmed = {row["id"] for row in client.list_items(collection_id, list_id=list_id)}
            except ReadCubeError:
                confirmed = set()
            for result in results:
                if result.get("item_id") in pending_membership:
                    if result["item_id"] in confirmed:
                        result["list_verified"] = True
                        records[result["doi"]]["membership"][list_id] = "verified"
                    else:
                        result["list_status"] = "needs_reconciliation"
                        stop = True
            save()
        return {
            "dry_run": dry_run,
            "collection_id": collection_id,
            "list_id": list_id,
            "input_count": len(dois),
            "unique_count": len(unique),
            "library_scan_requests": 1,
            "results": results,
            "stopped": stop,
            "journal_path": str(path) if not dry_run else None,
            "warning": "Other applications can write concurrently; upstream does not guarantee DOI uniqueness.",
        }
