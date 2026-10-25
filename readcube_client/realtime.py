"""Bayeux notifications, with full-scan reconciliation rather than a delta cursor.

The source contract is ReadCube Web 5.4.24 chunk-QD3Q3KF7.js. Nothing in this
protocol provides durable replay. Consumers must reconcile after every connection,
after a gap, periodically, and at the end of a bounded watch.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import deque
from contextlib import AbstractContextManager, suppress
from datetime import UTC, datetime
from typing import Any

import httpx

from .client import identifier
from .errors import AuthenticationError, ProtocolError, TransportError

try:
    from websockets.exceptions import WebSocketException
except ImportError:

    class WebSocketException(Exception):
        """Placeholder exception type when the optional dependency is absent."""


PUSH_HTTP = "https://push.readcube.com/bayeux"
PUSH_WS = "wss://push.readcube.com/bayeux"
CALLBACK = "__readcube_client__"


class RealtimeReconnect(TransportError):
    """The connection is no longer trustworthy; reconcile and re-handshake."""


class RealtimeStopped(ProtocolError):
    """The server explicitly advised no reconnect."""


def _base36(value: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    result = ""
    while value:
        value, digit = divmod(value, 36)
        result = digits[digit] + result
    return result or "0"


def _messages(value: Any) -> list[dict]:
    if not isinstance(value, list) or not value or any(not isinstance(x, dict) for x in value):
        raise ProtocolError("Bayeux: expected a nonempty message array")
    return value


def _jsonp(text: str) -> list[dict]:
    # The server uses the anti-hijacking prefix /**/ and optional whitespace.
    # Decode JSON only: never eval JavaScript or accept a caller-supplied callback.
    match = re.fullmatch(r"\s*(?:/\*\*/)?" + CALLBACK + r"\s*\((.*)\)\s*;?\s*", text, re.DOTALL)
    if not match:
        raise ProtocolError("Bayeux: invalid JSONP envelope")
    try:
        return _messages(json.loads(match.group(1)))
    except ValueError:
        raise ProtocolError("Bayeux: invalid handshake JSON") from None


class BayeuxListener(AbstractContextManager):
    """Read-only, evidence-gated subscription to exactly one collection.

    ``receive`` returns change *hints*, stripped of client/session identifiers.
    It does not advance a durable server cursor. Use ``watch_library`` for
    bounded notification-assisted full scans and recovery.
    """

    def __init__(self, client, collection_id: str, *, connection_factory=None):
        self.client = client
        self.collection_id = identifier(collection_id)
        self.channel = f"/production/collections/{self.collection_id}/changes"
        self._factory = connection_factory
        self._socket = None
        self._client_id = None
        self._counter = 1
        self._pending = {}
        self._queue = deque()
        self._interval = 0.0
        self._server_timeout = 25.0
        self._next_connect = None
        self._subscribed = False
        self._connected = False
        self.audit = []

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    def _advice(self, message):
        advice = message.get("advice")
        if advice is None:
            return
        if not isinstance(advice, dict):
            raise ProtocolError("Bayeux: invalid advice")
        for key, field in (("interval", "_interval"), ("timeout", "_server_timeout")):
            if key in advice:
                value = advice[key]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                    raise ProtocolError("Bayeux: invalid advice timing")
                # Do not retry early if the server requests an excessive wait.
                if value > 300_000:
                    raise RealtimeStopped("Bayeux: server timing exceeds the supported bound")
                setattr(self, field, value / 1000)
        if advice.get("reconnect") == "none":
            raise RealtimeStopped("Bayeux: server advised no reconnect")
        if advice.get("reconnect") == "handshake":
            raise RealtimeReconnect("Bayeux: server requested a new handshake")

    def connect(self):
        self.client._require("watch_changes")
        if not list(self.client.http.cookies.jar):
            raise AuthenticationError("Bayeux: no local authenticated session")
        if self._socket is not None:
            raise ProtocolError("Bayeux: listener is already connected")
        for name in ("websockets", "websockets.client", "httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.WARNING)
        handshake = {
            "channel": "/meta/handshake",
            "version": "1.0",
            "supportedConnectionTypes": [
                "websocket",
                "eventsource",
                "long-polling",
                "cross-origin-long-polling",
                "callback-polling",
            ],
            "id": "1",
        }
        try:
            response = self.client.http.get(
                PUSH_HTTP,
                params={"message": json.dumps(handshake, separators=(",", ":")), "jsonp": CALLBACK},
                follow_redirects=False,
            )
        except httpx.TransportError:
            raise RealtimeReconnect("Bayeux: handshake transport failed") from None
        if response.status_code in (401, 403):
            raise AuthenticationError("Bayeux: authentication or subscription access denied")
        if response.status_code != 200:
            raise RealtimeStopped(f"Bayeux: handshake HTTP {response.status_code}")
        messages = _jsonp(response.text)
        if len(messages) != 1:
            raise ProtocolError("Bayeux: expected one handshake response")
        message = messages[0]
        supported = message.get("supportedConnectionTypes")
        if (
            message.get("channel") != "/meta/handshake"
            or message.get("id") != "1"
            or message.get("successful") is not True
            or not isinstance(message.get("clientId"), str)
            or not message["clientId"]
            or not isinstance(supported, list)
            or "websocket" not in supported
        ):
            raise ProtocolError("Bayeux: unsuccessful or malformed handshake")
        self._advice(message)
        self._client_id = message["clientId"]
        self._counter = 1
        self._pending.clear()
        self._queue.clear()
        self._subscribed = self._connected = False
        self._next_connect = None
        factory = self._factory
        if factory is None:
            try:
                from websockets.sync.client import connect
            except ImportError:
                raise RuntimeError(
                    "Install readcube-agent-client[realtime] for WebSocket support"
                ) from None
            factory = connect
        # Use CookieJar's domain/path/expiry/secure rules, never copy every cookie.
        request = self.client.http.build_request("GET", PUSH_HTTP)
        headers = {}
        if request.headers.get("Cookie"):
            headers["Cookie"] = request.headers["Cookie"]
        try:
            self._socket = factory(
                PUSH_WS,
                origin="https://app.readcube.com",
                additional_headers=headers,
                open_timeout=min(self.client.settings.timeout, 30),
                close_timeout=2,
                max_size=1024 * 1024,
                logger=logging.getLogger("websockets.client"),
            )
            self._send("/meta/connect", connectionType="websocket")
            self._send("/meta/subscribe", subscription=self.channel)
            deadline = time.monotonic() + min(self.client.settings.timeout, 30)
            # /meta/connect may be held for the server's 25-second timeout.
            # Subscription acknowledgement is readiness; receive() continues to
            # validate the pending connect acknowledgement and heartbeat deadline.
            while not self._subscribed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RealtimeReconnect("Bayeux: subscribe acknowledgement timed out")
                self._receive_frame(remaining)
        except (ProtocolError, AuthenticationError, TransportError):
            self.close()
            raise
        except (OSError, WebSocketException):
            # WebSocket errors can embed complete headers or payloads.
            self.close()
            raise RealtimeReconnect("Bayeux: WebSocket connection failed") from None
        record = {
            "operation": "watch_changes",
            "http_status": 200,
            "at": datetime.now(UTC).isoformat(),
            "stage": "subscribed",
        }
        self.audit.append(record)
        self.client.audit.append(record.copy())

    def _send(self, channel, **extra):
        self._counter = self._counter + 1 if self._counter < 2**32 else 1
        message_id = _base36(self._counter)
        message = {"channel": channel, "id": message_id, "clientId": self._client_id, **extra}
        try:
            self._socket.send(json.dumps([message], separators=(",", ":")))
        except (OSError, WebSocketException):
            raise RealtimeReconnect("Bayeux: send failed") from None
        self._pending[message_id] = (channel, time.monotonic() + self._server_timeout + 5)

    def _process(self, messages):
        for message in messages:
            self._advice(message)
            channel = message.get("channel")
            if not isinstance(channel, str):
                raise ProtocolError("Bayeux: missing channel")
            if channel.startswith("/meta/"):
                pending = self._pending.pop(message.get("id"), None)
                if pending is None or pending[0] != channel:
                    raise ProtocolError("Bayeux: unmatched acknowledgement")
                if message.get("successful") is not True:
                    if channel == "/meta/subscribe":
                        raise AuthenticationError("Bayeux: collection subscription rejected")
                    raise RealtimeReconnect("Bayeux: unsuccessful control acknowledgement")
                if channel == "/meta/connect":
                    self._connected = True
                    self._next_connect = time.monotonic() + self._interval
                elif channel == "/meta/subscribe":
                    if message.get("subscription") != self.channel or self._subscribed:
                        raise ProtocolError("Bayeux: unexpected subscription acknowledgement")
                    self._subscribed = True
            elif channel == self.channel:
                data = message.get("data")
                changes = data.get("changes") if isinstance(data, dict) else None
                if not isinstance(changes, list) or any(not isinstance(c, dict) for c in changes):
                    raise ProtocolError("Bayeux: invalid collection change payload")
                self._queue.append(
                    [
                        {
                            key: value
                            for key, value in change.items()
                            if key in {"type", "id", "action"}
                        }
                        for change in changes
                    ]
                )
            else:
                raise ProtocolError("Bayeux: event for an unrelated channel")

    def _receive_frame(self, timeout):
        try:
            raw = self._socket.recv(timeout=timeout)
        except TimeoutError:
            return
        except (OSError, WebSocketException):
            raise RealtimeReconnect("Bayeux: connection closed or receive failed") from None
        try:
            self._process(_messages(json.loads(raw)))
        except (ValueError, TypeError, UnicodeDecodeError):
            raise ProtocolError("Bayeux: malformed WebSocket JSON") from None

    def receive(self, timeout: float = 30) -> list[dict] | None:
        """Receive one event, or None on a bounded idle timeout; maintain heartbeat."""
        if self._socket is None:
            raise ProtocolError("Bayeux: listener is not connected")
        if not 0 < timeout <= 60:
            raise ValueError("Receive timeout must be between 0 and 60 seconds")
        deadline = time.monotonic() + timeout
        while True:
            if self._queue:
                return self._queue.popleft()
            now = time.monotonic()
            if any(due <= now for _, due in self._pending.values()):
                raise RealtimeReconnect("Bayeux: missing server acknowledgement")
            if self._next_connect is not None and self._next_connect <= now:
                self._next_connect = None
                self._send("/meta/connect", connectionType="websocket")
            remaining = deadline - now
            if remaining <= 0:
                return None
            controls = [due - now for _, due in self._pending.values()]
            if self._next_connect is not None:
                controls.append(self._next_connect - now)
            self._receive_frame(max(0.001, min([remaining, *controls])))

    def close(self):
        socket, self._socket = self._socket, None
        if socket is not None:
            with suppress(OSError, WebSocketException):
                socket.send(
                    json.dumps([{"channel": "/meta/disconnect", "clientId": self._client_id}])
                )
            with suppress(OSError, WebSocketException):
                socket.close()
        self._pending.clear()
        self._client_id = None


def watch_library(
    client,
    collection_id: str,
    *,
    duration: float = 30,
    scan_interval: float = 15,
    max_reconnects: int = 2,
    listener_factory=BayeuxListener,
):
    """Yield full-scan deltas aided by notifications for a bounded interval.

    Complete scans happen on subscription, reconnect, notification, periodically,
    and at normal completion. Events never mark an item as deleted. On permanent
    failures the final successful scan is returned before the error propagates.
    The caller must keep iterating (or close the generator) to release the socket.
    """
    if not 0 < duration <= 3600 or not 1 <= scan_interval <= 300 or not 0 <= max_reconnects <= 5:
        raise ValueError("Invalid bounded watch parameters")
    client._require("watch_changes")
    identifier(collection_id)
    deadline = time.monotonic() + duration
    attempts = 0
    next_scan = time.monotonic()
    reason = "connected"
    listener = None
    notices = []

    def reconcile(why):
        return {
            "reason": why,
            "mode": "notification_assisted_full_scan",
            "changes": list(notices),
            "delta": client.sync_changes(collection_id).model_dump(),
        }

    try:
        while time.monotonic() < deadline:
            try:
                if listener is None:
                    listener = listener_factory(client, collection_id)
                    listener.connect()
                    yield reconcile(reason)
                    notices.clear()
                    next_scan = time.monotonic() + scan_interval
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                event = listener.receive(
                    min(5, remaining, max(0.001, next_scan - time.monotonic()))
                )
                if event is not None:
                    notices.extend(event)
                    # Coalesce events and allow the search index to catch up.
                    next_scan = min(next_scan, time.monotonic() + 1)
                if time.monotonic() >= next_scan:
                    yield reconcile("notification" if notices else "periodic")
                    notices.clear()
                    next_scan = time.monotonic() + scan_interval
            except RealtimeReconnect:
                if listener is not None:
                    listener.close()
                listener = None
                yield reconcile("connection_gap")
                notices.clear()
                if attempts >= max_reconnects:
                    raise
                attempts += 1
                delay = min(2 ** (attempts - 1), 8, max(0, deadline - time.monotonic()))
                time.sleep(delay)
                reason = "reconnected"
            except (AuthenticationError, ProtocolError):
                yield reconcile("stopped")
                raise
        yield reconcile("completed")
    finally:
        if listener is not None:
            listener.close()
