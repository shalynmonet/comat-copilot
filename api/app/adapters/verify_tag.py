"""Part-tag / data-plate photo reading.

Stores photographs a part's tag to confirm a low-confidence spare is
really there; a pilot wires this to a real vision call (Claude or
otherwise) that reads the tag and returns the same ExtractedTag shape.
Today there's no such call wired up, so `MockTagVerifyAdapter` "reads" a
small set of demo tag images -- deterministic, keyed by the uploaded
file's name, so the demo (and tests) never depend on real image bytes
or a live model. Anything it doesn't recognize comes back unreadable
(every field None), the same as a photo of something other than a tag
would for a real vision call. read_tag() in, an `ExtractedTag` out,
either way: a pilot sets TAG_VERIFY_ADAPTER=vision, registers a real
client with the same signature, and nothing that calls this module
changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Protocol

MISMATCH_FILENAME = "tag-ord-oxy-btl-02-mismatch.jpg"
MATCH_FILENAME = "tag-ord-oxy-btl-02-match.jpg"

# Pick-and-issue demo (see seed/generate.py's PICK_* constants): the
# shelf tag at the expected bin doesn't match what M3's record says
# should be there.
PICK_MISMATCH_FILENAME = "tag-pick-starter-gen-mismatch.jpg"
PICK_MATCH_FILENAME = "tag-pick-starter-gen-match.jpg"


@dataclass
class ExtractedTag:
    part_number: Optional[str]
    serial: Optional[str]
    condition: Optional[str]  # "serviceable" | "unserviceable" | "quarantined" | None if unreadable
    read_confidence: float  # the vision call's own confidence in the read, 0-1
    raw_text: str  # what the "model" read off the tag, shown to Stores next to the record


class TagVerifyAdapter(Protocol):
    def read_tag(self, image_filename: str) -> ExtractedTag: ...


_MOCK_READS: dict[str, ExtractedTag] = {
    # A deliberately wrong tag: one-liter bottle, not the 2L on record --
    # the demo's seeded phantom-part scenario (see seed/generate.py).
    MISMATCH_FILENAME: ExtractedTag(
        part_number="OXY-BTL-01",
        serial="SN-ORD-MISLABELED-01",
        condition="serviceable",
        read_confidence=0.93,
        raw_text="PART: OXY-BTL-01   S/N: SN-ORD-MISLABELED-01   COND: SERVICEABLE",
    ),
    MATCH_FILENAME: ExtractedTag(
        part_number="OXY-BTL-02",
        serial="INV-ORD-OXY-BTL-02-2",
        condition="serviceable",
        read_confidence=0.97,
        raw_text="PART: OXY-BTL-02   S/N: INV-ORD-OXY-BTL-02-2   COND: SERVICEABLE",
    ),
    # Pick-and-issue mismatch: the shelf at the expected bin actually has
    # a hydraulic pump, not the starter generator M3's record says.
    PICK_MISMATCH_FILENAME: ExtractedTag(
        part_number="HYD-PUMP-A",
        serial="SN-AUS-SHELF-MIXUP-01",
        condition="serviceable",
        read_confidence=0.9,
        raw_text="PART: HYD-PUMP-A   S/N: SN-AUS-SHELF-MIXUP-01   COND: SERVICEABLE",
    ),
    PICK_MATCH_FILENAME: ExtractedTag(
        part_number="STARTER-GEN",
        serial="INV-AUS-STARTER-GEN-1",
        condition="serviceable",
        read_confidence=0.96,
        raw_text="PART: STARTER-GEN   S/N: INV-AUS-STARTER-GEN-1   COND: SERVICEABLE",
    ),
}


class MockTagVerifyAdapter:
    source = "mock"

    def read_tag(self, image_filename: str) -> ExtractedTag:
        known = _MOCK_READS.get(image_filename)
        if known:
            return known
        # Not one of the seeded demo images -- a real vision call reading
        # something other than a clear part tag would come back empty
        # too, so this is treated as "missing" rather than guessing.
        return ExtractedTag(part_number=None, serial=None, condition=None, read_confidence=0.0, raw_text="")


def get_tag_verify_adapter() -> TagVerifyAdapter:
    """The pilot swap point: set TAG_VERIFY_ADAPTER=vision and register a
    real client here with the same read_tag() signature. Nothing that
    calls get_tag_verify_adapter() has to change."""
    backend = os.environ.get("TAG_VERIFY_ADAPTER", "mock")
    if backend == "mock":
        return MockTagVerifyAdapter()
    raise NotImplementedError(
        f"TAG_VERIFY_ADAPTER={backend!r} isn't wired up yet -- implement a TagVerifyAdapter for it."
    )
