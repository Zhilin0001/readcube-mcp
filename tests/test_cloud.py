import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

from readcube_mcp.cloud import OwnerVerifier, create_app

ENV = {
    "READCUBE_PUBLIC_URL": "https://example.com",
    "READCUBE_OAUTH_ISSUER": "https://issuer.example/",
    "READCUBE_OAUTH_JWKS_URL": "https://issuer.example/jwks",
    "READCUBE_OAUTH_AUDIENCE": "readcube",
    "READCUBE_OAUTH_SUBJECTS": "owner",
}


def test_bootstrap_blocks_all_mcp_calls():
    with TestClient(create_app({})) as c:
        assert c.get("/healthz").json() == {"status": "ok", "mcp_configured": False}
        assert c.post("/mcp", json={}).status_code == 503
        assert c.get("/.well-known/oauth-protected-resource").status_code == 503


def test_auth_gate_and_discovery():
    class Reject:
        def verify(self, token):
            return False

    with TestClient(create_app(ENV, Reject())) as c:
        assert (
            c.get("/.well-known/oauth-protected-resource/mcp").json()["resource"]
            == "https://example.com/mcp"
        )
        for headers in [{}, {"Authorization": "Bearer invalid"}]:
            r = c.post("/mcp", json={}, headers=headers)
            assert r.status_code == 401
            assert "resource_metadata=" in r.headers["www-authenticate"]


def test_jwt_checks_signature_expiry_issuer_audience_subject_scope():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    v = OwnerVerifier(
        ENV["READCUBE_OAUTH_ISSUER"], ENV["READCUBE_OAUTH_JWKS_URL"], "readcube", ["owner"]
    )

    class Keys:
        def get_signing_key_from_jwt(self, token):
            class K:
                pass

            k = K()
            k.key = key.public_key()
            return k

    v.keys = Keys()
    claims = {
        "iss": "https://issuer.example/",
        "aud": "readcube",
        "sub": "owner",
        "exp": int(time.time()) + 300,
        "scope": "readcube:access",
    }
    assert v.verify(jwt.encode(claims, key, algorithm="RS256"))
    for patch in [
        {"iss": "https://wrong.example/"},
        {"aud": "other"},
        {"sub": "stranger"},
        {"exp": 0},
        {"scope": "other"},
    ]:
        assert not v.verify(jwt.encode(claims | patch, key, algorithm="RS256"))
    assert not v.verify(jwt.encode(claims, other, algorithm="RS256"))
    assert not v.verify("not-a-token")


def test_download_capability_serves_only_generated_file_and_expires(make_client):
    import json
    from contextlib import contextmanager
    from pathlib import Path

    from readcube_client.artifacts import store_bytes

    client = make_client(lambda r: None)
    client.settings.artifact_base_url = "https://example.com"
    artifact = store_bytes(client, b"%PDF-test", "paper.pdf", "application/pdf")

    class Pool:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        @contextmanager
        def __call__(self):
            yield client

    class Reject:
        def verify(self, token):
            return False

    with TestClient(create_app(ENV, Reject(), client_pool=Pool())) as c:
        assert c.post("/mcp", json={}).status_code == 401
        path = "/artifacts/" + artifact["id"]
        response = c.get(path)
        assert response.status_code == 200 and response.content == b"%PDF-test"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["content-type"] == "application/pdf"
        assert c.get("/artifacts/not-a-token").status_code == 404
        manifest = Path(artifact["local_path"]).parent.parent / "links" / (artifact["id"] + ".json")
        record = json.loads(manifest.read_text())
        record["expires_at"] = 0
        manifest.write_text(json.dumps(record))
        assert c.get(path).status_code == 404
