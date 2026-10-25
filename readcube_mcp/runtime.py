"""Bounded HTTP connection reuse with current local authorization on every tool call."""

import hashlib
import json
import threading
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path

import httpx

from readcube_client import ReadCubeClient, Settings
from readcube_client.auth import load_cookies, session_fingerprint
from readcube_client.errors import AuthenticationError


class ReadCubeClientPool:
    """Exclusively lease clients without making slow tools block unrelated tools.

    The pool deliberately caches connections, not permission decisions. Settings,
    saved cookie validity and verification evidence are read again on checkout.
    Clients from an obsolete generation are closed when their current call ends.
    """

    def __init__(
        self,
        config_path: str | Path | None = None,
        *,
        max_clients: int = 4,
        settings_factory=None,
        client_factory=ReadCubeClient,
    ):
        if max_clients < 1:
            raise ValueError("max_clients must be positive")
        self._settings_factory = settings_factory or (lambda: Settings.from_toml(config_path))
        self._client_factory = client_factory
        self._max_clients = max_clients
        self._condition = threading.Condition()
        self._idle = []
        self._total = 0
        self._generation = None
        self._closed = False

    def _state(self):
        settings = self._settings_factory()
        path = settings.session_file
        # Check expiry and restrictive file mode even if contents/mtime did not change.
        cookies = load_cookies(path) if path.exists() or path.is_symlink() else httpx.Cookies()
        session = session_fingerprint(cookies)
        ledger = settings.verification_file
        key = hashlib.sha256(
            json.dumps(settings.model_dump(mode="json"), sort_keys=True).encode()
            + session.encode()
            + (ledger.read_bytes() if ledger.exists() else b"")
            + files("readcube_client").joinpath("endpoints.json").read_bytes()
        ).digest()
        return settings, session, key, cookies

    def _acquire(self):
        while True:
            with self._condition:
                if self._closed:
                    raise RuntimeError("ReadCube client pool is closed")
                try:
                    settings, session, generation, cookies = self._state()
                except Exception:
                    for client in self._idle:
                        client.close()
                    self._total -= len(self._idle)
                    self._idle.clear()
                    self._generation = None
                    self._condition.notify_all()
                    raise
                if generation != self._generation:
                    for client in self._idle:
                        client.close()
                    self._total -= len(self._idle)
                    self._idle.clear()
                    self._generation = generation
                while self._idle:
                    client = self._idle.pop()
                    if client.http.is_closed:
                        client.close()
                        self._total -= 1
                        continue
                    # ReadCube rotates its response cookie even on GET. Reapply the
                    # verified local jar for this invocation without discarding TLS
                    # connections. A changed *saved* session still retires the client.
                    client.http.cookies = cookies
                    client.audit.clear()
                    return client, generation
                if self._total < self._max_clients:
                    self._total += 1  # Reserve a slot while constructing outside the lock.
                else:
                    self._condition.wait()
                    continue
            try:
                client = self._client_factory(settings)
            except BaseException:
                with self._condition:
                    self._total -= 1
                    self._condition.notify_all()
                raise
            with self._condition:
                if (
                    self._closed
                    or generation != self._generation
                    or session_fingerprint(client.http.cookies) != session
                ):
                    client.close()
                    self._total -= 1
                    self._condition.notify_all()
                    if self._closed:
                        raise RuntimeError("ReadCube client pool is closed")
                    continue
            return client, generation

    def _release(self, client, generation, *, discard=False):
        with self._condition:
            if discard or self._closed or generation != self._generation or client.http.is_closed:
                client.close()
                self._total -= 1
            else:
                # A long-running server must not accumulate every historical request/import.
                del client.audit[:-100]
                for name in ("_recent_identifiers", "_recent_pdf_imports"):
                    recent = getattr(client, name, {})
                    for key in list(recent)[:-256]:
                        del recent[key]
                self._idle.append(client)
            self._condition.notify_all()

    @contextmanager
    def __call__(self):
        client, generation = self._acquire()
        discard = False
        try:
            yield client
        except AuthenticationError:
            discard = True
            raise
        finally:
            self._release(client, generation, discard=discard)

    def close(self):
        """Close idle clients now; active clients close as their leases finish."""
        with self._condition:
            self._closed = True
            for client in self._idle:
                client.close()
            self._total -= len(self._idle)
            self._idle.clear()
            self._condition.notify_all()

    def __enter__(self):
        with self._condition:
            if self._closed:
                raise RuntimeError("ReadCube client pool is closed")
        return self

    def __exit__(self, *args):
        self.close()
