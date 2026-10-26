"""Session-isolated immutable files and expiring, unguessable download capabilities."""

import hashlib
import json
import os
import re
import secrets
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from .auth import private_json_write
from .errors import ProtocolError


def artifact_root(client):
    namespace = hashlib.sha256(client.session.encode()).hexdigest()
    root = client.settings.state_dir / "artifacts" / namespace
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    return root


def safe_filename(name):
    name = Path(str(name).replace("\\", "/")).name
    name = re.sub(r'[\x00-\x1f\x7f";]', "_", name)[:180].strip(". ")
    return name or "readcube-file"


def atomic_bytes(path, content):
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".part-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def register_artifact(client, path, name, mime, *, ttl=600):
    root = artifact_root(client)
    path = path.resolve(strict=True)
    if not path.is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError("Artifact must be a generated file in this session")
    token = secrets.token_hex(24)
    record = {
        "id": token,
        "path": str(path.relative_to(root.resolve())),
        "name": safe_filename(name),
        "mime_type": mime,
        "size": path.stat().st_size,
        "expires_at": int(time.time()) + ttl,
    }
    private_json_write(root / "links" / (token + ".json"), record)
    record["local_path"] = str(path)
    base = client.settings.artifact_base_url
    if base:
        parsed = urlsplit(base)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.query
            or parsed.fragment
            or parsed.username
        ):
            raise ValueError("Artifact base URL must be an HTTPS origin/path without credentials")
        record["uri"] = base.rstrip("/") + "/artifacts/" + token
        record["download_url"] = record["uri"]
    else:
        record["uri"] = "readcube-file://artifacts/" + token
    record.pop("path")
    return record


def resolve_artifact(client, token):
    if not re.fullmatch(r"[a-f0-9]{48}", token):
        raise ValueError("Invalid artifact identifier")
    root = artifact_root(client).resolve()
    try:
        record = json.loads((root / "links" / (token + ".json")).read_text())
        path = (root / record["path"]).resolve(strict=True)
    except (FileNotFoundError, ValueError, KeyError):
        raise ValueError("Artifact is unavailable") from None
    if record["expires_at"] <= time.time() or not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Artifact expired or is unavailable")
    if path.stat().st_size != record["size"]:
        raise ProtocolError("Artifact integrity check failed")
    return path, record


def store_bytes(client, content, name, mime):
    digest = hashlib.sha256(content).hexdigest()
    path = artifact_root(client) / "blobs" / digest
    if not path.exists():
        atomic_bytes(path, content)
    return register_artifact(client, path, name, mime)
