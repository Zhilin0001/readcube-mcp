# Render (single owner)

Deploy the `readcube_mcp.cloud` entry point with Python 3.13.
Build: `pip install -r deploy/render-requirements.txt`
Start: `python -m readcube_mcp.cloud`
Health check: `/healthz`

No authentication configuration means `/mcp` returns 503. `/healthz` is liveness only.
Do not interpret a Live deployment as a working ReadCube integration.

## OAuth

Use an external OAuth provider supporting authorization code + PKCE and MCP-compatible discovery.
Register a ChatGPT OAuth client with the exact callback URL shown by ChatGPT.
Configure an API audience, RS256 access tokens, and the `readcube:access` scope.
Only the explicitly allowlisted owner's subject can use this deployment: everyone shares one
server-side ReadCube session. This is NOT a multi-user service.

Environment variables:
- READCUBE_PUBLIC_URL: the Render HTTPS origin (no trailing /mcp)
- READCUBE_OAUTH_ISSUER: exact token issuer, preserving any trailing slash
- READCUBE_OAUTH_JWKS_URL: provider's HTTPS JWKS endpoint
- READCUBE_OAUTH_AUDIENCE: expected API token audience
- READCUBE_OAUTH_SUBJECTS: comma-separated authorized owner subject IDs
- READCUBE_SESSION_FILE: `/etc/secrets/session.json`
- READCUBE_VERIFICATION_FILE: `/etc/secrets/verified.json`
- READCUBE_STATE_DIR: `/tmp/readcube-state` (ephemeral cache only)

After specific owner authorization, supply session.json and the matching session-bound verified.json
as Render secret files. Never commit either file or embed them in build artifacts. Cloud connectivity
and the existing session's validity need read-only verification; a changed session needs fresh
verification. The existing interactive login helper and extended verification flows are not a fully
tested unattended cloud onboarding mechanism. Update secret files when the session expires.

Keep READCUBE_WRITE_COLLECTIONS empty until specific writes are authorized. PDF upload tools refer
to the server filesystem, not files attached in ChatGPT; they need a separate authorized upload flow.

Free compute can sleep and has no durable writable disk; it is for connection testing. For always-on
use select a paid plan only with the owner's approval. OAuth provider costs are separate.
