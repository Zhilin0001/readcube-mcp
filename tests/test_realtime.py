import json
from types import SimpleNamespace

import httpx
import pytest

from readcube_client.errors import AuthenticationError, ProtocolError, UnverifiedEndpointError
from readcube_client.realtime import (
    CALLBACK,
    PUSH_WS,
    BayeuxListener,
    RealtimeReconnect,
    RealtimeStopped,
    _base36,
    _jsonp,
    watch_library,
)


def handshake(**kwargs):
    return {
        "channel": "/meta/handshake",
        "id": "1",
        "successful": True,
        "clientId": "secret-client-id",
        "supportedConnectionTypes": ["websocket"],
        "advice": {"reconnect": "retry", "interval": 0, "timeout": 25000},
        **kwargs,
    }


class FakeSocket:
    def __init__(self, frames=()):
        self.frames = list(frames)
        self.sent = []
        self.closed = False

    def send(self, value):
        self.sent.extend(json.loads(value))

    def recv(self, timeout):
        if not self.frames:
            raise TimeoutError
        frame = self.frames.pop(0)
        if isinstance(frame, Exception):
            raise frame
        return json.dumps(frame)

    def close(self):
        self.closed = True


def acknowledgements(cid="c"):
    return [
        {"channel": "/meta/connect", "id": "2", "successful": True},
        {
            "channel": "/meta/subscribe",
            "id": "3",
            "successful": True,
            "subscription": f"/production/collections/{cid}/changes",
        },
    ]


@pytest.fixture
def setup_listener():
    clients = []

    def setup(*, frames=None, response=None, require=None):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(
                200, text=f"{CALLBACK} ({json.dumps([response or handshake()])});"
            )

        cookies = httpx.Cookies()
        cookies.set("session", "secret-cookie", domain=".readcube.com", path="/")
        cookies.set("foreign", "private", domain="other.example", path="/")
        http = httpx.Client(transport=httpx.MockTransport(handler), cookies=cookies)
        clients.append(http)
        client = SimpleNamespace(
            http=http,
            settings=SimpleNamespace(timeout=1),
            audit=[],
            _require=require or (lambda name: None),
        )
        socket = FakeSocket([acknowledgements()] if frames is None else frames)
        connection_args = []

        def factory(*args, **kwargs):
            connection_args.append((args, kwargs))
            return socket

        listener = BayeuxListener(client, "c", connection_factory=factory)
        return listener, socket, requests, connection_args

    yield setup
    for http in clients:
        http.close()


def test_handshake_subscription_scopes_cookies_and_redacts_output(setup_listener):
    listener, socket, requests, args = setup_listener()
    with listener:
        assert listener.audit[0]["stage"] == "subscribed"
        assert args[0][0] == (PUSH_WS,)
        assert args[0][1]["additional_headers"]["Cookie"] == "session=secret-cookie"
        assert "foreign" not in requests[0].headers["Cookie"]
        assert socket.sent[0]["channel"] == "/meta/connect"
        assert socket.sent[1]["subscription"] == "/production/collections/c/changes"
    assert socket.closed
    assert "secret" not in json.dumps(listener.audit)


def test_requires_evidence_before_network(setup_listener):
    def require(name):
        assert name == "watch_changes"
        raise UnverifiedEndpointError("unverified")

    listener, socket, requests, args = setup_listener(require=require)
    with pytest.raises(UnverifiedEndpointError):
        listener.connect()
    assert requests == [] and args == [] and socket.sent == []


@pytest.mark.parametrize(
    "raw",
    [
        "alert(1)",
        "other([])",
        f"{CALLBACK}([]);alert(1)",
        f"{CALLBACK}({{}})",
        f"{CALLBACK}([])",
        f"{CALLBACK}([1])",
    ],
)
def test_jsonp_is_not_executable_or_permissive(raw):
    with pytest.raises(ProtocolError):
        _jsonp(raw)


def test_real_jsonp_prefix_is_accepted():
    expected = [{"channel": "/meta/handshake"}]
    assert _jsonp(f"/**/{CALLBACK}({json.dumps(expected)})") == expected


def test_base36_ids():
    assert _base36(35) == "z" and _base36(36) == "10"


@pytest.mark.parametrize(
    "changed",
    [
        {"successful": False},
        {"clientId": ""},
        {"id": "incorrect"},
        {"supportedConnectionTypes": ["long-polling"]},
    ],
)
def test_invalid_handshake_not_used_to_open_socket(setup_listener, changed):
    listener, _, _, args = setup_listener(response=handshake(**changed))
    with pytest.raises(ProtocolError):
        listener.connect()
    assert args == []


def test_event_strips_session_identifiers_and_maintains_heartbeat(setup_listener):
    event = {
        "channel": "/production/collections/c/changes",
        "data": {
            "sync_client_id": "secret",
            "changes": [
                {"type": "item", "id": "i", "action": "updated", "clientId": "secret"},
            ],
        },
    }
    listener, socket, _, _ = setup_listener(frames=[acknowledgements(), [event]])
    with listener:
        assert listener.receive(0.1) == [{"type": "item", "id": "i", "action": "updated"}]
        assert socket.sent[2]["channel"] == "/meta/connect"


def test_unrelated_channel_fails_closed(setup_listener):
    event = {"channel": "/production/collections/other/changes", "data": {"changes": []}}
    listener, _, _, _ = setup_listener(frames=[acknowledgements(), [event]])
    with listener, pytest.raises(ProtocolError, match="unrelated"):
        listener.receive(0.1)


def test_subscribe_denied_is_not_retried(setup_listener):
    acks = acknowledgements()
    acks[1]["successful"] = False
    acks[1]["error"] = "secret backend response"
    listener, socket, _, _ = setup_listener(frames=[acks])
    with pytest.raises(AuthenticationError) as caught:
        listener.connect()
    assert "secret" not in str(caught.value)
    assert socket.closed


def test_control_acknowledgement_must_match_request(setup_listener):
    acks = acknowledgements()
    acks[0]["id"] = "unrelated"
    listener, _, _, _ = setup_listener(frames=[acks])
    with pytest.raises(ProtocolError, match="unmatched"):
        listener.connect()


def test_subscribe_can_finish_before_long_connect_ack(setup_listener):
    listener, _, _, _ = setup_listener(frames=[[acknowledgements()[1]]])
    with listener:
        assert listener._subscribed
        assert not listener._connected
        assert listener._pending["2"][0] == "/meta/connect"


def test_missing_heartbeat_requires_reconciliation(setup_listener):
    listener, _, _, _ = setup_listener()
    with listener:
        listener._pending["lost"] = ("/meta/connect", -1)
        with pytest.raises(RealtimeReconnect, match="missing server"):
            listener.receive(0.1)


def test_idle_receive_returns_none(setup_listener):
    listener, _, _, _ = setup_listener()
    with listener:
        assert listener.receive(0.001) is None


@pytest.mark.parametrize(
    "advice,error",
    [
        ({"reconnect": "none"}, RealtimeStopped),
        ({"reconnect": "handshake"}, RealtimeReconnect),
        ({"timeout": -1}, ProtocolError),
        ({"interval": 1_000_000}, RealtimeStopped),
    ],
)
def test_advice_respected(setup_listener, advice, error):
    listener, _, _, args = setup_listener(response=handshake(advice=advice))
    with pytest.raises(error):
        listener.connect()
    assert args == []


def test_lost_connection_redacts_transport_exception(setup_listener):
    listener, _, _, _ = setup_listener(frames=[acknowledgements(), OSError("secret-cookie")])
    with listener, pytest.raises(RealtimeReconnect) as caught:
        listener.receive(0.1)
    assert "secret" not in str(caught.value)


def test_watch_reconciles_gaps_reconnects_and_final_state(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("readcube_client.realtime.time.monotonic", lambda: now[0])
    monkeypatch.setattr(
        "readcube_client.realtime.time.sleep", lambda t: now.__setitem__(0, now[0] + t)
    )
    instances = []

    class Listener:
        def __init__(self, *args):
            self.index = len(instances)
            self.closed = False
            instances.append(self)

        def connect(self):
            pass

        def receive(self, timeout):
            now[0] += timeout
            if self.index == 0:
                raise RealtimeReconnect("lost")

        def close(self):
            self.closed = True

    scans = []

    def scan(cid):
        scans.append(cid)
        return SimpleNamespace(model_dump=lambda: {"missing": [], "mode": "full_scan_local_diff"})

    client = SimpleNamespace(_require=lambda name: None, sync_changes=scan)
    rows = list(watch_library(client, "c", duration=6, scan_interval=2, listener_factory=Listener))
    reasons = [r["reason"] for r in rows]
    assert reasons[:3] == ["connected", "connection_gap", "reconnected"]
    assert "periodic" in reasons and reasons[-1] == "completed"
    assert len(scans) == len(rows)
    assert all(x.closed for x in instances)
    assert all(r["mode"] == "notification_assisted_full_scan" for r in rows)


def test_watch_does_not_retry_advice_none(monkeypatch):
    count = []

    class Listener:
        def __init__(self, *args):
            count.append(1)

        def connect(self):
            raise RealtimeStopped("stop")

        def close(self):
            pass

    client = SimpleNamespace(
        _require=lambda name: None,
        sync_changes=lambda cid: SimpleNamespace(model_dump=dict),
    )
    iterator = watch_library(client, "c", listener_factory=Listener)
    assert next(iterator)["reason"] == "stopped"
    with pytest.raises(RealtimeStopped):
        next(iterator)
    assert count == [1]
