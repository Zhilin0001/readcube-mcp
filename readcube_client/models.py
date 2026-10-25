from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Item(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    collection_id: str | None = None
    article: dict[str, Any] = Field(default_factory=dict)
    ext_ids: dict[str, Any] = Field(default_factory=dict)
    user_data: dict[str, Any] = Field(default_factory=dict)
    files: list[dict[str, Any]] = Field(default_factory=list)


class WritePlan(BaseModel):
    dry_run: bool = True
    operation: str
    evidence: str
    verified: bool
    collection_id: str
    method: str
    path: str
    body: dict[str, Any]
    note: str = "No network request sent. UNVERIFIED operations remain unavailable in production."


class WriteAuthorization(BaseModel):
    collection_id: str
    authorized: bool = False
    confirmation: str | None = None


class SyncDelta(BaseModel):
    mode: str = "full_scan_local_diff"
    added: list[str]
    changed: list[str]
    missing: list[str]
    total: int
    warning: str = (
        "Missing does not prove deletion; permissions or concurrent changes may hide records."
    )
