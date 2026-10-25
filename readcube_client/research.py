"""Explicit opt-in research surface. Never imported or exposed by MCP."""

from datetime import UTC, datetime

from .auth import private_json_write
from .client import ReadCubeClient
from .errors import ProtocolError


class ResearchClient(ReadCubeClient):
    def __init__(self, *args, acknowledge_unverified: bool = False, **kwargs):
        if acknowledge_unverified is not True:
            raise ValueError("Research execution requires acknowledge_unverified=True")
        super().__init__(*args, **kwargs)
        self._research = True

    def record_verified(self, operation: str, *, semantic_check: bool, detail: str):
        if not semantic_check:
            raise ProtocolError("Cannot promote an operation without its semantic check")
        successful = [
            event
            for event in self.audit
            if event["operation"] == operation and 200 <= event["http_status"] < 300
        ]
        if not successful:
            raise ProtocolError("Cannot promote an operation without an actual successful request")
        self.registry.records[operation] = {
            "status": "VERIFIED",
            "contract_sha256": self.registry.signature(operation),
            "semantic_check": True,
            "checked_at": datetime.now(UTC).isoformat(),
            "detail": detail,
            "http_status": successful[-1]["http_status"],
        }
        private_json_write(
            self.settings.verification_file,
            {"session": self.session, "operations": self.registry.records},
        )
