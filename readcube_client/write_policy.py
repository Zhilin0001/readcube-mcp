"""Local, persistent per-collection write restrictions."""

import json
from types import SimpleNamespace

from .auth import private_json_write
from .errors import AuthorizationError, ProtocolError
from .workflow import _state_lock


def _path(client):
    return client.settings.state_dir / "write-policy.json"


def blocked_collections(client):
    path = _path(client)
    if path.is_symlink():
        raise ProtocolError("Write policy cannot be a symlink")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        raise ProtocolError("Cannot read write policy; writes are blocked") from None
    if (
        not isinstance(data, dict)
        or data.get("version") != 1
        or not isinstance(data.get("blocked"), list)
        or not all(isinstance(v, str) and v for v in data["blocked"])
    ):
        raise ProtocolError("Invalid write policy; writes are blocked")
    return data["blocked"]


def write_allowed(client, collection_id):
    from .client import identifier

    identifier(collection_id)
    return collection_id not in blocked_collections(client) and (
        client.settings.write_policy == "all" or collection_id in client.settings.write_collections
    )


def set_library_access(client, collection, allow, *, authorized=False, dry_run=True):
    """Resolve an exact library name/ID and preview or persist a targeted restriction."""
    if not isinstance(collection, str) or not collection.strip() or type(allow) is not bool:
        raise ValueError("Provide a library name or ID and an allow/deny decision")
    target = collection.strip().casefold()
    rows = client.list_collections()
    matches = [
        row
        for row in rows
        if isinstance(row.get("id"), str)
        and not row.get("deleted")
        and (row["id"].casefold() == target or str(row.get("name") or "").casefold() == target)
    ]
    if len(matches) != 1:
        raise ValueError("Library name or ID must identify exactly one accessible collection")
    row = matches[0]
    from .client import identifier

    identifier(row["id"])
    # Use an account-independent lock: restrictions are shared by all client
    # processes using this local state directory, including after reauthentication.
    lock_client = SimpleNamespace(settings=client.settings, session="write-policy-v1")
    with _state_lock(lock_client, "global", ".policy.lock"):
        blocked = set(blocked_collections(client))
        before = row["id"] not in blocked and (
            client.settings.write_policy == "all" or row["id"] in client.settings.write_collections
        )
        after = allow and (
            client.settings.write_policy == "all" or row["id"] in client.settings.write_collections
        )
        result = {
            "collection_id": row["id"],
            "collection_name": row.get("name"),
            "dry_run": dry_run,
            "write_allowed_before": before,
            "write_allowed_after": after,
            "requested_allow": allow,
            "write_policy": client.settings.write_policy,
        }
        if dry_run:
            return result
        if not authorized:
            raise AuthorizationError(
                "Explicit authorization is required to change library write access"
            )
        if allow:
            blocked.discard(row["id"])
        else:
            blocked.add(row["id"])
        private_json_write(_path(client), {"version": 1, "blocked": sorted(blocked)})
        return result | {"changed": before != after, "saved": True}
