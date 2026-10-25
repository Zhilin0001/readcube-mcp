"""Explicit test-library changes to verify notification and disconnected-gap recovery."""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from readcube_client import Settings, WriteAuthorization
from readcube_client.auth import private_json_write
from readcube_client.realtime import BayeuxListener, watch_library
from readcube_client.research import ResearchClient

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--execute", action="store_true")
args = parser.parse_args()
r = json.loads(Path("research/private/extended-resources.json").read_text())
cid, iid = r["collection_id"], r["pdf_item_id"]
with ResearchClient(Settings.from_toml("readcube.local.toml"), acknowledge_unverified=True) as c:
    assert any(
        x["id"] == cid and x["name"] == "Codex API Test 2026-10-24" for x in c.list_collections()
    )
    w = {"authorization": WriteAuthorization(collection_id=cid, authorized=True), "dry_run": False}
    original = c.get_item(cid, iid).get("user_data", {}).get("notes", "")
    plan = c.update_notes(cid, iid, "Codex controlled realtime notification verification")
    private_json_write(
        Path("research/private/realtime-write-preview.json"),
        {
            "old_notes": original,
            "plan": plan.model_dump(),
            "gap_notes": "Codex disconnected-gap verification",
        },
    )
    if not args.execute:
        print(json.dumps({"dry_run": True, "plans_saved": True}))
        raise SystemExit(0)
    with BayeuxListener(c, cid) as listener:
        print(json.dumps({"stage": "subscribed"}), flush=True)
        c.update_notes(cid, iid, "Codex controlled realtime notification verification", **w)
        deadline = time.monotonic() + 45
        received = False
        while time.monotonic() < deadline:
            event = listener.receive(min(10, deadline - time.monotonic()))
            if event and any(
                e.get("id") == iid and e.get("type") == "item" and e.get("action") == "updated"
                for e in event
            ):
                received = True
                break
        assert received, "Target item update notification not received"
        assert (
            c.get_item(cid, iid)["user_data"]["notes"]
            == "Codex controlled realtime notification verification"
        )
        print(json.dumps({"stage": "controlled_update_event", "verified": True}), flush=True)
    time.sleep(2)
    c.sync_changes(cid)
    c.update_notes(cid, iid, "Codex disconnected-gap verification", **w)
    time.sleep(2)
    scans = list(watch_library(c, cid, duration=5, scan_interval=2))
    assert any(iid in scan["delta"]["changed"] for scan in scans), (
        "Disconnected change not found by reconciliation"
    )
    c.record_verified(
        "watch_changes",
        semantic_check=True,
        detail="Real Bayeux subscription received controlled item updated event; fresh connection full scan recovered a note change made while disconnected",
    )
    private_json_write(
        Path("research/private/realtime-controlled.json"),
        {
            "event_received": received,
            "gap_recovered": True,
            "scan_reasons": [s["reason"] for s in scans],
            "audit": c.audit,
        },
    )
    print(
        json.dumps(
            {"operation": "watch_changes", "verified": True, "disconnected_gap_recovered": True}
        ),
        flush=True,
    )
