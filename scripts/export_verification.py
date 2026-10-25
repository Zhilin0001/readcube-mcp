"""Export sanitized capability evidence; never copy session secrets/fingerprints."""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from readcube_client import ReadCubeClient, Settings

ROOT = Path(__file__).resolve().parents[1]
with ReadCubeClient(Settings.from_toml(ROOT / "readcube.local.toml")) as client:
    capabilities = client.capabilities()
    operations = {}
    rows = ["| 操作 | 方法 | Host | 路径 | 本轮状态 |", "|---|---|---|---|---|"]
    for name, status in capabilities.items():
        record = client.registry.records.get(name, {})
        operations[name] = {
            **status,
            **{
                k: v
                for k, v in record.items()
                if k
                in {
                    "contract_sha256",
                    "semantic_check",
                    "checked_at",
                    "detail",
                    "http_status",
                    "readback_http_status",
                }
            },
        }
        entry = client.registry.catalog[name]
        rows.append(
            f"| `{name}` | {entry.get('method', '—')} | `{entry.get('host', '—')}` | `{entry.get('path', '—')}` | {status['verification']} / {status['evidence']} |"
        )
    document = {
        "date": "2026-10-25",
        "exported_at": datetime.now(UTC).isoformat(),
        "frontend_version": "5.4.24",
        "verified_count": sum(x["verification"] == "VERIFIED" for x in capabilities.values()),
        "catalog_count": len(capabilities),
        "operations": operations,
    }
    (ROOT / "docs/verification-results.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    )
    table = "\n".join(rows) + "\n"
    (ROOT / "docs/api-table.md").write_text(table)
    api = ROOT / "docs/readcube-api.md"
    text = api.read_text()
    start = text.index("| 操作 | 方法 | Host | 路径 | 本轮状态 |")
    end = text.index("\n\n", start)
    api.write_text(text[:start] + table + text[end:])
    print(
        json.dumps({"verified": document["verified_count"], "catalog": document["catalog_count"]})
    )
