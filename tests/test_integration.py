import os

import pytest

from readcube_client import ReadCubeClient

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("READCUBE_RUN_INTEGRATION") != "1",
        reason="Requires explicit live read-only test opt-in",
    ),
]


def test_live_verified_collections():
    with ReadCubeClient() as client:
        rows = client.list_collections()
        assert all(isinstance(row.get("id"), str) for row in rows)


def test_live_library_and_annotations():
    collection_id = os.getenv("READCUBE_TEST_COLLECTION")
    if not collection_id:
        pytest.skip("READCUBE_TEST_COLLECTION is required")
    with ReadCubeClient() as client:
        assert isinstance(client.list_lists(collection_id), list)
        items = client.list_items(collection_id)
        if items:
            item = client.get_item(collection_id, items[0]["id"])
            assert item["id"] == items[0]["id"]
            assert isinstance(client.get_annotations(collection_id, item["id"]), list)
