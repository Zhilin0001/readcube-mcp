import httpx
import pytest

from readcube_client import ReadCubeClient, Settings


@pytest.fixture
def make_client(tmp_path):
    """Transport mocks test code only; fixture verification never reaches a live ledger."""
    clients = []

    def make(handler, verified=(), **overrides):
        settings = Settings(
            _env_file=None,
            verification_file=tmp_path / "verified.json",
            state_dir=tmp_path / "state",
            min_interval=0,
            retries=0,
            **overrides,
        )
        http = httpx.Client(
            transport=httpx.MockTransport(handler),
            cookies={"fake_test_session": "not-a-real-token"},
        )
        client = ReadCubeClient(settings, http=http)
        for name in verified:
            client.registry.records[name] = {
                "status": "VERIFIED",
                "semantic_check": True,
                "contract_sha256": client.registry.signature(name),
            }
        clients.append(http)
        return client

    yield make
    for client in clients:
        client.close()
