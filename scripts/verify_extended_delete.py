"""Delete only two explicitly confirmed test targets from the private preview."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from readcube_client import Settings, WriteAuthorization
from readcube_client.auth import private_json_write
from readcube_client.errors import APIError
from readcube_client.research import ResearchClient

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--execute", action="store_true")
parser.add_argument("--confirm-note", default="")
parser.add_argument("--confirm-smartlist", default="")
args = parser.parse_args()
r = json.loads(Path("research/private/extended-delete-preview.json").read_text())
cid, iid = r["collection_id"], r["item_id"]
note, smart = r["note_annotation_id"], r["smartlist_id"]
with ResearchClient(Settings.from_toml("readcube.local.toml"), acknowledge_unverified=True) as c:
    assert any(
        x["id"] == cid and x["name"] == "Codex API Test 2026-10-24" for x in c.list_collections()
    )
    plans = [
        c.delete_annotation(cid, iid, note).model_dump(),
        c.delete_smartlist(cid, smart).model_dump(),
    ]
    private_json_write(
        Path("research/private/extended-delete-execution-plan.json"), {"plans": plans}
    )
    if not args.execute:
        print(json.dumps({"dry_run": True, "plan_saved": True}))
        raise SystemExit(0)
    if args.confirm_note != f"DELETE {note}" or args.confirm_smartlist != f"DELETE {smart}":
        raise ValueError("Separate exact confirmations required for both targets")

    def save_audit():
        private_json_write(
            Path("research/private/extended-delete-results.json"), {"audit": c.audit}
        )

    c.delete_annotation(
        cid,
        iid,
        note,
        authorization=WriteAuthorization(
            collection_id=cid, authorized=True, confirmation=args.confirm_note
        ),
        dry_run=False,
    )
    save_audit()
    remaining = c.get_annotations(cid, iid)
    assert all(a["id"] != note or a.get("deleted") for a in remaining)
    c.record_verified(
        "delete_annotation",
        semantic_check=True,
        detail="Confirmed synthetic note DELETE absent in annotation GET",
    )
    c.delete_smartlist(
        cid,
        smart,
        authorization=WriteAuthorization(
            collection_id=cid, authorized=True, confirmation=args.confirm_smartlist
        ),
        dry_run=False,
    )
    save_audit()
    try:
        found = c.get_smartlist(cid, smart)
        absent = found.get("deleted") is True
    except APIError as e:
        if e.status != 404:
            raise
        absent = True
    assert absent and all(x["id"] != smart for x in c.list_smartlists(cid))
    c.record_verified(
        "delete_smartlist",
        semantic_check=True,
        detail="Confirmed Smart List DELETE by independent GET tombstone/404 and list absence",
    )
    save_audit()
    print(json.dumps({"delete_annotation": "VERIFIED", "delete_smartlist": "VERIFIED"}))
