"""Private, single-owner HTTP deployment with external OAuth JWT verification."""

import asyncio
import os
import shutil
import tempfile
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import jwt
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route

from readcube_client import Settings
from readcube_client.artifacts import resolve_artifact
from readcube_mcp.runtime import ReadCubeClientPool
from readcube_mcp.server import create_server


def https_url(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "OAuth URLs must be absolute HTTPS URLs without credentials, query or fragment"
        )
    return value


class OwnerVerifier:
    def __init__(self, issuer, jwks_url, audience, subjects):
        self.issuer = https_url(issuer)
        self.audience = audience
        self.subjects = set(subjects)
        self.keys = jwt.PyJWKClient(https_url(jwks_url), timeout=5, lifespan=300)

    def verify(self, token):
        try:
            key = self.keys.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
            return (
                claims["sub"] in self.subjects
                and "readcube:access" in claims.get("scope", "").split()
            )
        except (jwt.PyJWTError, ValueError, TypeError, OSError):
            return False


class ProtectedMCP:
    def __init__(self, app, verifier, public_url):
        self.app, self.verifier = app, verifier
        self.metadata_url = public_url + "/.well-known/oauth-protected-resource/mcp"

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        auth = request.headers.get("authorization", "")
        scheme, _, token = auth.partition(" ")
        valid = scheme.lower() == "bearer" and bool(token) and len(token) <= 16384
        if not valid or not await asyncio.to_thread(self.verifier.verify, token):
            response = JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={
                    "WWW-Authenticate": 'Bearer resource_metadata="'
                    + self.metadata_url
                    + '", scope="readcube:access"',
                    "Cache-Control": "no-store",
                },
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_app(env=None, verifier=None, client_pool=None):
    env = os.environ if env is None else env
    required = [
        "READCUBE_PUBLIC_URL",
        "READCUBE_OAUTH_ISSUER",
        "READCUBE_OAUTH_JWKS_URL",
        "READCUBE_OAUTH_AUDIENCE",
        "READCUBE_OAUTH_SUBJECTS",
    ]
    ready = all(env.get(k) for k in required)

    async def health(request):
        # Liveness only: never implies ReadCube login or endpoint verification succeeded.
        return JSONResponse({"status": "ok", "mcp_configured": ready})

    async def unavailable(request):
        return JSONResponse({"error": "MCP authentication is not configured"}, status_code=503)

    routes = [Route("/healthz", health)]
    if not ready:
        routes.append(
            Route("/{path:path}", unavailable, methods=["GET", "POST", "DELETE", "OPTIONS"])
        )
        return Starlette(routes=routes)

    public_url = https_url(env["READCUBE_PUBLIC_URL"]).rstrip("/")
    issuer = https_url(env["READCUBE_OAUTH_ISSUER"])
    subjects = [x.strip() for x in env["READCUBE_OAUTH_SUBJECTS"].split(",") if x.strip()]
    if not subjects:
        raise ValueError("At least one explicitly authorized OAuth subject is required")
    verifier = verifier or OwnerVerifier(
        issuer, env["READCUBE_OAUTH_JWKS_URL"], env["READCUBE_OAUTH_AUDIENCE"], subjects
    )

    def settings_factory():
        settings = Settings()
        settings.artifact_base_url = public_url
        return settings

    pool = client_pool or ReadCubeClientPool(settings_factory=settings_factory)
    server = create_server(pool, artifact_origin=public_url)
    mcp_app = server.streamable_http_app(stateless_http=True, json_response=True, host="0.0.0.0")

    async def metadata(request):
        return JSONResponse(
            {
                "resource": public_url + "/mcp",
                "authorization_servers": [issuer],
                "scopes_supported": ["readcube:access"],
                "bearer_methods_supported": ["header"],
            }
        )

    async def artifact_download(request):
        # The random, ten-minute capability is the download credential. It exposes
        # generated files only, never ReadCube cookies or signed storage URLs.
        try:
            with pool() as client:
                path, record = resolve_artifact(client, request.path_params["artifact_id"])
            return FileResponse(
                path,
                media_type=record["mime_type"],
                filename=record["name"],
                headers={
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                    "Access-Control-Allow-Origin": "*",
                },
            )
        except (ValueError, OSError):
            return JSONResponse({"error": "file unavailable"}, status_code=404)

    @asynccontextmanager
    async def lifespan(app):
        with pool:
            async with mcp_app.router.lifespan_context(mcp_app):
                yield

    routes.extend(
        [
            Route("/.well-known/oauth-protected-resource/mcp", metadata),
            Route("/.well-known/oauth-protected-resource", metadata),
            Route("/artifacts/{artifact_id}", artifact_download, methods=["GET", "HEAD"]),
            Mount("/", app=ProtectedMCP(mcp_app, verifier, public_url)),
        ]
    )
    return Starlette(routes=routes, lifespan=lifespan)


@contextmanager
def render_session(env, source="/etc/secrets/session.json"):
    """Stage the explicitly configured platform secret as a private regular file."""
    if env.get("READCUBE_SESSION_FILE") != source:
        yield
        return
    with tempfile.TemporaryDirectory(prefix="readcube-session-") as directory:
        target = Path(directory) / "session.json"
        # The source is Render's trusted secret mount, which uses symlinks.
        with open(source, "rb") as incoming, target.open("xb") as outgoing:
            os.chmod(target, 0o600)
            shutil.copyfileobj(incoming, outgoing)
        env["READCUBE_SESSION_FILE"] = str(target)
        try:
            yield
        finally:
            env["READCUBE_SESSION_FILE"] = source


def main():
    with render_session(os.environ):
        uvicorn.run(
            create_app(),
            host="0.0.0.0",
            port=int(os.environ.get("PORT", "10000")),
            access_log=False,
        )


if __name__ == "__main__":
    main()
