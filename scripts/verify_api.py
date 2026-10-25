#!/usr/bin/env python3
"""Opt-in live verification. Test writes are scoped to one explicitly named collection."""

import argparse
import hashlib
import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from readcube_client import Settings, WriteAuthorization
from readcube_client.auth import private_json_write
from readcube_client.errors import ProtocolError, ReadCubeError
from readcube_client.research import ResearchClient

TEST_NAME = "Codex API Test 2026-10-24"


def make_test_pdf(path: Path):
    stream = b"BT /F1 14 Tf 40 760 Td (ReadCube SDK synthetic upload test. No personal data.) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    result = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    start = len(result)
    result.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \n".encode())
    result.extend(f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(result)


def verify(args):
    settings = Settings.from_toml(args.config)
    evidence = {
        "at": datetime.now(UTC).isoformat(),
        "mode": "live" if args.execute else "dry_run",
        "target_name": args.test_collection,
        "results": [],
        "deletions": "not_requested",
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    def report(name, result, **detail):
        evidence["results"].append({"operation": name, "result": result, **detail})
        private_json_write(output, evidence)
        print(json.dumps(evidence["results"][-1], ensure_ascii=False), flush=True)

    with ResearchClient(settings, acknowledge_unverified=True) as client:

        def await_readback(predicate, timeout=30):
            deadline = time.monotonic() + timeout
            while True:
                if predicate():
                    return True
                if time.monotonic() >= deadline:
                    return False
                time.sleep(2)

        def checked(name, condition, detail):
            if not condition:
                raise ProtocolError(f"{name}: semantic readback did not match")
            client.record_verified(name, semantic_check=True, detail=detail)
            report(name, "VERIFIED", check=detail)

        collections = client.list_collections()
        checked(
            "list_collections",
            all(isinstance(c.get("id"), str) for c in collections),
            "Authenticated JSON collection IDs",
        )
        matches = [c for c in collections if c.get("name") == args.test_collection]
        if len(matches) > 1:
            raise ProtocolError(
                "Multiple test collections with the same name; specify a unique name"
            )
        plan = {
            "target": args.test_collection,
            "create_collection": not bool(matches),
            "operations": [
                "read_items",
                "import_DOI",
                "create_synthetic_item",
                "set_notes",
                "set_add_remove_tags",
                "create_rename_list",
                "add_remove_list_membership",
                "upload_synthetic_pdf",
                "get_annotations",
                "local_snapshot_diff",
            ],
            "no_deletion": True,
            "no_external_invites": True,
        }
        private_json_write(output.with_suffix(".plan.json"), plan)
        report("plan", "DRY_RUN_RECORDED", plan=plan)
        if not args.execute:
            return
        if args.authorized_test_collection != args.test_collection:
            raise ProtocolError("--authorized-test-collection must exactly match --test-collection")
        if not matches:
            # Collection creation uses the reviewed form fields; no invites or sharing.
            body = {
                "name": args.test_collection,
                "description": "Disposable API validation records only",
                "invite_users": {},
                "add_users": {},
                "add_groups": {},
                "discoverable": False,
                "send_email": False,
            }
            created = client._request("create_collection", body=body)["collection"]
            collection_id = created["id"]
            matches = [c for c in client.list_collections() if c["id"] == collection_id]
            checked(
                "create_collection",
                bool(matches) and matches[0].get("name") == args.test_collection,
                "Created private named test library, found by authenticated readback",
            )
        else:
            collection_id = matches[0]["id"]
        settings.write_collections = [collection_id]
        authorization = WriteAuthorization(collection_id=collection_id, authorized=True)
        writes = {"authorization": authorization, "dry_run": False}
        private_json_write(
            Path("research/private/test-target.json"),
            {"collection_id": collection_id, "name": args.test_collection},
        )
        rows = client.list_items(collection_id)
        checked(
            "list_items",
            all(isinstance(i["id"], str) for i in rows),
            "Complete scroll traversal with valid item objects",
        )
        lists = client.list_lists(collection_id)
        checked(
            "list_lists",
            all(isinstance(i.get("id"), str) for i in lists),
            "List array with resource IDs",
        )
        result = client.import_by_doi(collection_id, args.doi, **writes)
        if result.get("created") is False:
            imported = result["matches"][0]
            report("import_identifier", "SKIPPED_EXISTING", needs_review=result["needs_review"])
        else:
            imported = result["item"]
            actual = client.get_item(collection_id, imported["id"])
            from readcube_client import normalize_doi

            checked(
                "import_identifier",
                normalize_doi(actual["ext_ids"]["doi"]) == normalize_doi(args.doi),
                "DOI imported and preserved in independent item GET",
            )
        item_id = imported["id"]
        actual = client.get_item(collection_id, item_id)
        checked("get_item", actual["id"] == item_id, "GET returned the requested item ID")
        duplicate = client.import_by_doi(collection_id, args.doi, **writes)
        report(
            "doi_deduplication",
            "VERIFIED" if duplicate.get("created") is False else "FAILED",
            needs_review=duplicate.get("needs_review", False),
        )
        title = f"Codex synthetic API record {uuid.uuid4()}"
        synthetic = client.create_item(
            collection_id, {"item_type": "article", "article": {"title": title}}, **writes
        )["item"]
        synthetic_id = synthetic["id"]
        checked(
            "create_item",
            client.get_item(collection_id, synthetic_id)["article"]["title"] == title,
            "Synthetic metadata record created and title read back",
        )
        private_json_write(
            Path("research/private/test-resources.json"),
            {
                "collection_id": collection_id,
                "imported_item_id": item_id,
                "synthetic_item_id": synthetic_id,
            },
        )
        # Mutate only the newly created synthetic reference.
        notes = f"ReadCube SDK verification {datetime.now(UTC).isoformat()}"
        client.update_notes(collection_id, synthetic_id, notes, **writes)
        checked(
            "update_notes",
            client.get_item(collection_id, synthetic_id)["user_data"].get("notes") == notes,
            "Notes independently read back",
        )
        for operation, fn, values, expected in [
            ("set_tags", client.update_tags, ["codex-api-test"], {"codex-api-test"}),
            ("add_tags", client.add_tags, ["temporary"], {"codex-api-test", "temporary"}),
            ("remove_tags", client.remove_tags, ["temporary"], {"codex-api-test"}),
        ]:
            fn(collection_id, synthetic_id, values, **writes)
            checked(
                operation,
                set(client.get_item(collection_id, synthetic_id)["user_data"].get("tags", []))
                == expected,
                "Tag set independently read back",
            )
        renamed = title + " updated"
        client.update_metadata(
            collection_id, synthetic_id, {"article": {"title": renamed}}, **writes
        )
        checked(
            "update_metadata",
            client.get_item(collection_id, synthetic_id)["article"]["title"] == renamed,
            "PATCH metadata persisted in independent GET",
        )
        list_name = "SDK validation " + str(uuid.uuid4())[:8]
        created_list = client.create_list(collection_id, list_name, **writes)["list"]
        list_id = created_list["id"]
        private_json_write(
            Path("research/private/test-resources.json"),
            {
                "collection_id": collection_id,
                "imported_item_id": item_id,
                "synthetic_item_id": synthetic_id,
                "list_id": list_id,
            },
        )
        checked(
            "create_list",
            any(
                i["id"] == list_id and i["name"] == list_name
                for i in client.list_lists(collection_id)
            ),
            "New List present in collection list GET",
        )
        client.rename_list(collection_id, list_id, list_name + " renamed", **writes)
        checked(
            "rename_list",
            any(
                i["id"] == list_id and i["name"] == list_name + " renamed"
                for i in client.list_lists(collection_id)
            ),
            "Renamed List independently read back",
        )
        client.add_to_list(collection_id, list_id, synthetic_id, **writes)
        present = await_readback(
            lambda: (
                synthetic_id in {i["id"] for i in client.list_items(collection_id, list_id=list_id)}
            )
        )
        members = client.list_items(collection_id, list_id=list_id)
        checked(
            "add_to_list",
            present,
            "Membership verified by list item GET after bounded propagation wait",
        )
        checked(
            "list_list_items",
            all(isinstance(i["id"], str) for i in members),
            "List item response parsed and membership present",
        )
        client.remove_from_list(collection_id, list_id, synthetic_id, **writes)
        checked(
            "remove_from_list",
            await_readback(
                lambda: (
                    synthetic_id
                    not in {i["id"] for i in client.list_items(collection_id, list_id=list_id)}
                )
            ),
            "Membership removal verified by list item GET",
        )
        annotations = client.get_annotations(collection_id, synthetic_id)
        checked(
            "get_annotations",
            isinstance(annotations, list),
            "Annotation array read; empty does not validate highlight fields",
        )
        pdf = Path("research/private/synthetic-test.pdf")
        make_test_pdf(pdf)
        try:
            uploaded = client.upload_pdf(collection_id, synthetic_id, pdf, **writes)
            checked(
                "add_file",
                uploaded.get("associated") is True,
                "Uploaded SHA-256 confirmed in item files",
            )
            if any(e["operation"] == "uploads_pending" for e in client.audit):
                checked(
                    "uploads_pending",
                    True,
                    "Upload processing reached completed and association was read back",
                )
            checked(
                "upload_pdf_flow",
                uploaded.get("associated") is True,
                "PDF SHA-256 confirmed after the complete upload workflow",
            )
            report(
                "upload_pdf_flow",
                "VERIFIED" if uploaded.get("associated") else "UNVERIFIED",
                sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),
            )
        except ReadCubeError as error:
            report("upload_pdf_flow", "UNVERIFIED", reason=str(error))
        first = client.sync_changes(collection_id)
        second = client.sync_changes(collection_id)
        report(
            "snapshot_diff",
            "VERIFIED"
            if not (second.added or second.changed or second.missing)
            else "CHANGED_DURING_SCAN",
            first_total=first.total,
            second_total=second.total,
            mode=second.mode,
        )
        evidence["audit"] = client.audit
        evidence["capabilities"] = client.capabilities()
        private_json_write(output, evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--test-collection", default=TEST_NAME)
    parser.add_argument("--authorized-test-collection")
    parser.add_argument("--doi", default="10.1038/nature12373")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", default="research/private/live-validation.json")
    args = parser.parse_args()
    try:
        verify(args)
    except (ReadCubeError, ValueError, KeyError) as error:
        print(
            json.dumps({"status": "FAILED", "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
