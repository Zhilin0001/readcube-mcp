#!/usr/bin/env python3
"""Explicit, read-only live verification of original PDF download and text extraction."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from readcube_client import Settings
from readcube_client.auth import private_json_write
from readcube_client.errors import ProtocolError, ReadCubeError
from readcube_client.research import ResearchClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--collection-id", required=True)
    parser.add_argument("--item-id", required=True)
    parser.add_argument("--sha256")
    parser.add_argument("--expected-text", help="Optional known text for extraction validation")
    parser.add_argument("--acknowledge-unverified", action="store_true", required=True)
    parser.add_argument("--output", default="research/private/pdf-verification.json")
    args = parser.parse_args()
    with ResearchClient(Settings.from_toml(args.config), acknowledge_unverified=True) as client:
        cid, iid = args.collection_id, args.item_id
        item = client.get_item(cid, iid)
        expected = {f.get("sha256") for f in item.get("files", [])}
        urls = client.files_with_urls(cid, [iid])[iid]
        if not urls or any(f.get("sha256") not in expected for f in urls):
            raise ProtocolError("File URL response does not match the selected reference")
        downloaded = client.download_pdf(cid, iid, sha256=args.sha256)
        # Record endpoint evidence only after real original-byte verification.
        client.record_verified(
            "files_with_urls",
            semantic_check=True,
            detail="Authenticated attachment lookup and original PDF download; selected reference SHA-256 and PDF signature matched. No remote mutation.",
        )
        text = client.read_pdf(cid, iid, sha256=downloaded["sha256"], max_chars=200000)
        if args.expected_text and args.expected_text not in text["text"]:
            raise ProtocolError("Expected validation text is absent from the requested text range")
        result = {
            "status": "VERIFIED",
            "remote_mutations": False,
            "sha256": downloaded["sha256"],
            "bytes": downloaded["artifact"]["size"],
            "pages": text["page_count"],
            "ocr_required": text["ocr_required"],
            "expected_text_checked": bool(args.expected_text),
        }
        private_json_write(Path(args.output), result)
        print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except (ReadCubeError, ValueError, OSError) as error:
        raise SystemExit(str(error)) from None
