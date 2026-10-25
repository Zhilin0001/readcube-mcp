import math

import pytest
from pydantic import ValidationError

from readcube_client.annotations import (
    PageNote,
    TextHighlight,
    annotation_data,
    point_from_top_left,
    rect_from_top_left,
    single_annotation_body,
)


def test_note_envelope_preserves_item_and_file_scope():
    note = PageNote(sha256="a" * 64, page_start=0, position=(72, 720), note="Test note")
    body = single_annotation_body("test-item", note)
    assert body["type"] == "item"
    assert body["action_name"] == "add_annotation"
    assert body["data"][0]["id"] == "test-item"
    assert body["data"][0]["data"]["sha256"] == "a" * 64
    assert body["data"][0]["data"]["position"] == [72, 720]
    assert body["data"][0]["data"]["has_note"] is True
    assert "item_id" not in body["data"][0]["data"]


def test_highlight_note_and_coordinate_conversion():
    rect = rect_from_top_left(72, 40, 100, 12, page_height=792)
    highlight = TextHighlight(
        sha256="b" * 64,
        page_start=0,
        page_end=0,
        rects=[rect],
        text="Synthetic text",
        note="Explanation",
    )
    assert annotation_data(highlight)["has_note"] is True
    assert rect == [72, 740, 100, 12]
    assert point_from_top_left(72, 40, page_height=792) == [72, 752]
    assert point_from_top_left(72.125, 40, page_height=792) == [72.13, 752]


@pytest.mark.parametrize(
    "changes",
    [
        {"sha256": "not-a-file-hash"},
        {"page_start": -1},
        {"page_start": True},
        {"position": (math.nan, 3)},
        {"position": (4, math.inf)},
        {"position": (-1, 10)},
        {"note": ""},
        {"color_id": 99},
        {"rects": [[1, 2, 3, 4]]},
    ],
)
def test_note_rejects_invalid_geometry_or_mixed_shape(changes):
    data = {"type": "note", "sha256": "a" * 64, "page_start": 0, "position": [72, 720], "note": "x"}
    with pytest.raises(ValidationError):
        annotation_data(data | changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"page_end": 1},
        {"rects": []},
        {"rects": [[1, 2, 0, 4]]},
        {"rects": [[1, 2, 3, -4]]},
        {"has_note": True},
    ],
)
def test_highlight_rejects_unreviewed_or_invalid_shapes(changes):
    data = {
        "type": "highlight",
        "sha256": "a" * 64,
        "page_start": 0,
        "page_end": 0,
        "rects": [[1, 2, 3, 4]],
    }
    with pytest.raises(ValidationError):
        annotation_data(data | changes)


def test_conversion_rejects_nonfinite_and_out_of_page_inputs():
    with pytest.raises(ValueError):
        point_from_top_left(1, 793, page_height=792)
    with pytest.raises(ValueError):
        rect_from_top_left(1, 780, 10, 20, page_height=792)
    with pytest.raises(ValueError):
        rect_from_top_left(1, 2, math.inf, 4, page_height=792)
