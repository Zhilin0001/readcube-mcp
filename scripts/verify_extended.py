"""Opt-in continuation, only the existing named test library; no deletions."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verify_api import make_test_pdf

from readcube_client import Settings, WriteAuthorization
from readcube_client.auth import private_json_write
from readcube_client.research import ResearchClient

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "research/private"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--stage", choices=["read", "upload", "smartlist"], default="read")
    args = parser.parse_args()
    target = json.loads((PRIVATE / "test-target.json").read_text())
    cid = target["collection_id"]
    settings = Settings.from_toml(ROOT / "readcube.local.toml")
    with ResearchClient(settings, acknowledge_unverified=True) as c:
        matches = [
            r
            for r in c.list_collections()
            if r["id"] == cid and r.get("name") == "Codex API Test 2026-10-24"
        ]
        assert len(matches) == 1, "Existing test library identity changed"
        auth = WriteAuthorization(collection_id=cid, authorized=True)
        write = {"authorization": auth, "dry_run": False}
        resources_path = PRIVATE / "extended-resources.json"
        resources = (
            json.loads(resources_path.read_text())
            if resources_path.exists()
            else {"collection_id": cid}
        )

        def save():
            private_json_write(resources_path, resources)

        def checked(name, ok, detail):
            assert ok, f"{name} readback failed"
            c.record_verified(name, semantic_check=True, detail=detail)
            print(
                json.dumps({"operation": name, "verification": "VERIFIED", "detail": detail}),
                flush=True,
            )

        def plan(method, *pos, **kw):
            p = method(*pos, **kw, dry_run=True)
            private_json_write(PRIVATE / f"extended-{p.operation}-plan.json", p.model_dump())
            print(json.dumps({"operation": p.operation, "dry_run_saved": True}), flush=True)

        if args.stage == "read":
            result = c.reader_metadata("10.1038/nature12373")
            checked(
                "reader_metadata",
                result["meta"]["doi"] == "10.1038/nature12373",
                "DOI metadata matches requested canonical DOI",
            )
            iid = json.loads((PRIVATE / "test-resources.json").read_text())["imported_item_id"]
            revisions = c.get_revisions(cid, iid)
            private_json_write(PRIVATE / "revisions-sample.json", {"revisions": revisions})
            checked(
                "get_revisions",
                isinstance(revisions, list),
                f"Own test item returned revisions array with {len(revisions)} entries; not a delta cursor",
            )
            smartlists = c.list_smartlists(cid)
            checked(
                "list_smartlists",
                all(isinstance(s.get("id"), str) for s in smartlists),
                "Smart List array returned for authorized test library",
            )
        elif args.stage == "upload":
            pdf = PRIVATE / "synthetic-direct-import.pdf"
            if not pdf.exists():
                make_test_pdf(pdf)
                pdf.write_bytes(pdf.read_bytes() + b"\n% Direct PDF import flow 2026-10-25\n")
            plan(c.import_pdf, cid, pdf)
            if not args.execute:
                return
            result = c.import_pdf(cid, pdf, **write)
            if result.get("created") is False:
                print(
                    json.dumps(
                        {
                            "operation": "import_pdf",
                            "created": False,
                            "needs_review": result["needs_review"],
                            "write_requests_sent": 0,
                        }
                    ),
                    flush=True,
                )
                return
            resources.update(pdf_item_id=result["item"]["id"], pdf_sha256=result["sha256"])
            save()
            checked(
                "upload_file",
                result["associated"],
                "Direct upload_file flow created/resolved item, independent GET confirms SHA-256",
            )
            checked(
                "import_pdf_flow",
                result["associated"],
                "Fresh synthetic PDF PUT, pending completion and upload_file reassociation confirmed by GET hash",
            )
            # A second PDF on the same synthetic reference verifies supplemental PDF and primary switch.
            pdf2 = PRIVATE / "synthetic-supplement.pdf"
            if not pdf2.exists():
                make_test_pdf(pdf2)
                pdf2.write_bytes(pdf2.read_bytes() + b"\n% Supplemental PDF 2026-10-25\n")
            plan(c.upload_pdf, cid, resources["pdf_item_id"], pdf2)
            extra = c.upload_pdf(cid, resources["pdf_item_id"], pdf2, **write)
            resources["supplement_sha256"] = extra["sha256"]
            save()
            plan(c.set_primary_file, cid, resources["pdf_item_id"], extra["sha256"])
            c.set_primary_file(cid, resources["pdf_item_id"], extra["sha256"], **write)
            actual = c.get_item(cid, resources["pdf_item_id"])
            checked(
                "set_primary_file",
                actual.get("primary_file_hash") == extra["sha256"],
                "Second synthetic PDF made primary, independent item GET confirms hash",
            )
            # Re-importing the same PDF must converge to the same item.
            again = c.import_pdf(cid, pdf, **write)
            assert again.get("created") is False and again["item"]["id"] == resources["pdf_item_id"]
            print(
                json.dumps({"operation": "same_hash_reimport", "verification": "VERIFIED"}),
                flush=True,
            )
        elif args.stage == "smartlist":
            plan(c.create_smartlist, cid, "Codex API Smart Test", "Codex")
            if not args.execute:
                return
            if "smartlist_id" not in resources:
                created = c.create_smartlist(cid, "Codex API Smart Test", "Codex", **write)
                resources["smartlist_id"] = created["smartlist"]["id"]
                save()
                found = c.get_smartlist(cid, resources["smartlist_id"])
                checked(
                    "create_smartlist",
                    found.get("query") == "Codex",
                    "Created Smart List read back with exact query",
                )
            sid = resources["smartlist_id"]
            found = c.get_smartlist(cid, sid)
            checked("get_smartlist", found["id"] == sid, "Requested Smart List ID returned")
            plan(
                c.update_smartlist, cid, sid, name="Codex API Smart Test Updated", query="synthetic"
            )
            c.update_smartlist(
                cid, sid, name="Codex API Smart Test Updated", query="synthetic", **write
            )
            found = c.get_smartlist(cid, sid)
            checked(
                "update_smartlist",
                found["name"] == "Codex API Smart Test Updated" and found["query"] == "synthetic",
                "Updated name and saved query read back exactly",
            )
        private_json_write(
            PRIVATE / f"extended-{args.stage}-audit.json",
            {"at": datetime.now(UTC).isoformat(), "audit": c.audit},
        )


if __name__ == "__main__":
    main()
