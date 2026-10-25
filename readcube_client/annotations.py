"""Reviewed annotation request shapes; network availability remains evidence-gated.

The sync API uses zero-based pages and unrotated original-page coordinates
with a bottom-left origin. These models validate outgoing requests only; they
must not be used to discard unknown fields from annotations read from the API.
"""

import math
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

Coordinate = Annotated[float, Field(ge=0, allow_inf_nan=False)]
PositiveCoordinate = Annotated[float, Field(gt=0, allow_inf_nan=False)]
AnnotationColor = Literal[1, 2, 3, 4, 5, 6, 10]


class _Annotation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, frozen=True)

    id: str = Field(default_factory=lambda: str(uuid4()), pattern=r"^[A-Za-z0-9_:-]+$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_start: int = Field(ge=0, strict=True)
    color_id: AnnotationColor = 1


class PageNote(_Annotation):
    """A sticky note at [x, y] in the sync coordinate system."""

    type: Literal["note"] = "note"
    has_note: Literal[True] = True
    note: str = Field(min_length=1)
    position: tuple[Coordinate, Coordinate]


class TextHighlight(_Annotation):
    """A single-page highlight with [x, y, width, height] rectangles."""

    type: Literal["highlight"] = "highlight"
    page_end: int = Field(ge=0, strict=True)
    rects: list[tuple[Coordinate, Coordinate, PositiveCoordinate, PositiveCoordinate]] = Field(
        min_length=1
    )
    text: str | None = None
    has_note: bool = False
    note: str = ""

    @model_validator(mode="before")
    @classmethod
    def default_note_flag(cls, value):
        if isinstance(value, dict) and "has_note" not in value:
            value = dict(value, has_note=bool(value.get("note")))
        return value

    @model_validator(mode="after")
    def supported_shape(self):
        if self.page_end != self.page_start:
            raise ValueError("Only single-page highlight geometry has been reviewed")
        if self.has_note != bool(self.note):
            raise ValueError("has_note must match the presence of note text")
        return self


_ANNOTATION = TypeAdapter(Annotated[PageNote | TextHighlight, Field(discriminator="type")])


def annotation_data(value: dict | PageNote | TextHighlight) -> dict:
    """Validate a supported outgoing annotation without making a request."""
    return _ANNOTATION.validate_python(value).model_dump(mode="json", exclude_none=True)


def single_annotation_body(item_id: str, value: dict | PageNote | TextHighlight) -> dict:
    """Build the frontend's bulk_single envelope, restricted to one item."""
    if not re.fullmatch(r"[A-Za-z0-9_:-]+", item_id):
        raise ValueError("Invalid item_id")
    return {
        "type": "item",
        "action_name": "add_annotation",
        "data": [{"id": item_id, "data": annotation_data(value)}],
    }


def point_from_top_left(x: float, y: float, *, page_height: float) -> list[float]:
    """Convert an unrotated original-page point to sync coordinates.

    Screen pixels must first be converted to original-page units by the caller.
    Rotation, cropping, and PDF user-unit conversion are deliberately not guessed.
    """
    if not all(math.isfinite(v) for v in (x, y, page_height)):
        raise ValueError("Coordinates must be finite")
    if x < 0 or page_height <= 0 or not 0 <= y <= page_height:
        raise ValueError("Point is outside the supported page coordinates")
    return [_round_coordinate(x), _round_coordinate(page_height - y)]


def rect_from_top_left(
    x: float, y: float, width: float, height: float, *, page_height: float
) -> list[float]:
    """Convert [left, top, width, height] to the frontend's sync rectangle."""
    if not all(math.isfinite(v) for v in (x, y, width, height, page_height)):
        raise ValueError("Coordinates must be finite")
    if x < 0 or y < 0 or width <= 0 or height <= 0 or page_height < y + height:
        raise ValueError("Rectangle is outside the supported page coordinates")
    return [
        _round_coordinate(x),
        _round_coordinate(page_height - y - height),
        _round_coordinate(width),
        _round_coordinate(height),
    ]


def _round_coordinate(value: float) -> float:
    # The frontend's round10 uses Math.round, rather than Python's ties-to-even.
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
