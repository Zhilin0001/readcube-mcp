"""Create two synthetic annotations; delete only via separately authorized follow-up."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from readcube_client import Settings, WriteAuthorization
from readcube_client.annotations import PageNote, TextHighlight, annotation_data
from readcube_client.auth import private_json_write
from readcube_client.research import ResearchClient

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--execute", action="store_true")
args = parser.parse_args()
p = Path("research/private/extended-resources.json")
r = json.loads(p.read_text())
cid, iid = r["collection_id"], r["pdf_item_id"]
with ResearchClient(Settings.from_toml("readcube.local.toml"), acknowledge_unverified=True) as c:
    assert any(
        x["id"] == cid and x["name"] == "Codex API Test 2026-10-24" for x in c.list_collections()
    )
    w = {"authorization": WriteAuthorization(collection_id=cid, authorized=True), "dry_run": False}
    note = PageNote(
        sha256=r["pdf_sha256"],
        page_start=0,
        position=(72, 720),
        note="Synthetic API note 2026-10-25",
    )
    highlight = TextHighlight(
        sha256=r["pdf_sha256"],
        page_start=0,
        page_end=0,
        rects=[(40, 756, 380, 16)],
        text="ReadCube SDK synthetic upload test. No personal data.",
    )
    for annotation in [note, highlight]:
        plan = c.create_annotation(cid, iid, annotation)
        private_json_write(
            Path(f"research/private/annotation-{annotation.type}-plan.json"), plan.model_dump()
        )
        if not args.execute:
            continue
        c.create_annotation(cid, iid, annotation, **w)
        r.setdefault("annotation_ids", []).append(annotation.id)
        private_json_write(p, r)
        found = [a for a in c.get_annotations(cid, iid) if a["id"] == annotation.id]
        expected = annotation_data(annotation)
        assert len(found) == 1 and all(found[0].get(k) == v for k, v in expected.items()), (
            "Annotation fields changed"
        )
        print(json.dumps({"type": annotation.type, "created_and_readback": True}), flush=True)
    if not args.execute:
        print(json.dumps({"dry_run": True, "plans_saved": True}))
        raise SystemExit(0)
    c.record_verified(
        "create_annotation",
        semantic_check=True,
        detail="Synthetic PDF note and single-page highlight created via bulk_single; all outgoing fields match annotation GET",
    )
    patch = {"note": "Synthetic API note updated", "color_id": 2}
    plan = c.update_annotation(cid, iid, note.id, patch)
    private_json_write(Path("research/private/annotation-update-plan.json"), plan.model_dump())
    c.update_annotation(cid, iid, note.id, patch, **w)
    found = next(a for a in c.get_annotations(cid, iid) if a["id"] == note.id)
    assert all(found[k] == v for k, v in patch.items())
    c.record_verified(
        "update_annotation",
        semantic_check=True,
        detail="Synthetic PDF note text and color PATCH independently confirmed by annotations GET",
    )
    private_json_write(Path("research/private/annotation-audit.json"), {"audit": c.audit})
    print(json.dumps({"operation": "update_annotation", "verified": True}), flush=True)
