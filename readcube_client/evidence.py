import hashlib
import json
from importlib.resources import files
from pathlib import Path

from .errors import UnverifiedEndpointError


class EvidenceRegistry:
    """Local audit records are scoped to the session and exact request contract."""

    def __init__(self, path: Path, session: str):
        self.path = path
        self.session = session
        self.catalog = json.loads(files("readcube_client").joinpath("endpoints.json").read_text())
        self.records = {}
        if path.exists():
            document = json.loads(path.read_text())
            if document.get("session") == session:
                self.records = document.get("operations", {})

    def signature(self, name: str) -> str:
        return hashlib.sha256(json.dumps(self.catalog[name], sort_keys=True).encode()).hexdigest()

    def verified(self, name: str) -> bool:
        record = self.records.get(name, {})
        return (
            name in self.catalog
            and record.get("status") == "VERIFIED"
            and record.get("contract_sha256") == self.signature(name)
            and record.get("semantic_check") is True
        )

    def require(self, name: str, research: bool = False) -> None:
        entry = self.catalog.get(name)
        if not entry or entry["evidence"] not in ("SOURCE_CONFIRMED", "VERIFIED"):
            raise UnverifiedEndpointError(f"{name}: UNKNOWN; no established request contract")
        if not self.verified(name) and not research:
            raise UnverifiedEndpointError(
                f"{name}: UNVERIFIED ({entry['evidence']}); run the explicit verification script first"
            )

    def capabilities(self) -> dict:
        return {
            name: {
                "evidence": entry["evidence"],
                "verification": "VERIFIED" if self.verified(name) else "UNVERIFIED",
            }
            for name, entry in self.catalog.items()
        }
