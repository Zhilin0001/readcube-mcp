import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from importlib.resources import files
from pathlib import Path

from .errors import UnverifiedEndpointError

# Exact contracts independently exercised end-to-end with synthetic PDFs.
# Only the PDF upload context may use this historical project evidence.
_UPLOAD_CONTRACTS = {
    "list_items": "5d8aca0b0e302a5ea7d4e9670872833fde5e289ae4507a18ad06c15f64cff0d0",
    "get_item": "b1b79b5f91b88d5f96cf728e0f47bd064469a0c95843af81e22372d4aa85ef2f",
    "add_file": "8e5ded4f65f40654cf9f893c3f4d061886f8612c760f26f0507fd5345b8fd7c0",
    "upload_file": "d95b228ee2f40ca92d17a9be127f4315f681822aed71352ef3c1945cf0fc5f79",
    "uploads_pending": "354688198ea9c2cfc1fae315a2de8eb80f56643fb3ca99c7a6c3469ec8e8932d",
    "upload_pdf_flow": "b003143e276c060eb4dbd0f841266e1adb377d85f078fc3279e7df627041e3d5",
    "import_pdf_flow": "d8c1d4f1a51d76f52fdcd46b8075276ca618edd5e76d5ffdbe41f0e44300d2fc",
}
_PDF_SCOPES = {
    "upload_pdf_flow": frozenset({"get_item", "add_file", "uploads_pending", "upload_pdf_flow"}),
    "import_pdf_flow": frozenset(
        {"list_items", "get_item", "upload_file", "uploads_pending", "import_pdf_flow"}
    ),
}


class EvidenceRegistry:
    """Local audit records are scoped to the session and exact request contract."""

    def __init__(self, path: Path, session: str, *, client_version: str = "5.4.24"):
        self.path = path
        self.session = session
        self.client_version = client_version
        self.catalog = json.loads(files("readcube_client").joinpath("endpoints.json").read_text())
        self._pdf_scope = ContextVar("readcube_pdf_contract_scope", default=None)
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

    def project_pdf_verified(self, flow: str) -> bool:
        return (
            self.client_version == "5.4.24"
            and flow in _PDF_SCOPES
            and all(
                name in self.catalog
                and self.catalog[name].get("evidence") == "SOURCE_CONFIRMED"
                and self.signature(name) == _UPLOAD_CONTRACTS[name]
                for name in _PDF_SCOPES[flow]
            )
        )

    @contextmanager
    def pdf_upload_scope(self, flow: str):
        token = self._pdf_scope.set(flow if self.project_pdf_verified(flow) else None)
        try:
            yield
        finally:
            self._pdf_scope.reset(token)

    def allowed_in_current_scope(self, name: str) -> bool:
        flow = self._pdf_scope.get()
        return self.verified(name) or (
            flow in _PDF_SCOPES and name in _PDF_SCOPES[flow] and self.project_pdf_verified(flow)
        )

    def require(self, name: str, research: bool = False) -> None:
        entry = self.catalog.get(name)
        if not entry or entry["evidence"] not in ("SOURCE_CONFIRMED", "VERIFIED"):
            raise UnverifiedEndpointError(f"{name}: UNKNOWN; no established request contract")
        if not self.allowed_in_current_scope(name) and not research:
            raise UnverifiedEndpointError(
                f"{name}: UNVERIFIED ({entry['evidence']}); run the explicit verification script first"
            )

    def capabilities(self) -> dict:
        result = {}
        for name, entry in self.catalog.items():
            session_verified = self.verified(name)
            project_flows = [
                flow
                for flow, ops in _PDF_SCOPES.items()
                if name in ops and self.project_pdf_verified(flow)
            ]
            result[name] = {
                "evidence": entry["evidence"],
                "verification": "VERIFIED"
                if session_verified
                else ("PROJECT_VERIFIED_FOR_PDF" if project_flows else "UNVERIFIED"),
                "session_verification": "VERIFIED" if session_verified else "UNVERIFIED",
                "project_verified_pdf_flows": project_flows,
            }
        return result
