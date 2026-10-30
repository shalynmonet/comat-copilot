"""Resolving a PickSlip photo: replaces the paper slip's hand-written
location/serial and the retype into M3 with a photo of the shelf tag,
read by the same mocked tag adapter the shipment-verification flow uses
(app/adapters/verify_tag.py) -- a photo is a photo, whether Stores is
confirming a committed spare or a mechanic is picking one off the shelf.

A match completes the issue through M3 (app/adapters/m3_adapter.py) and
raises that inventory record's confidence, the same way a verify_task
match does. A mismatch -- or an empty shelf, which reads back the same
unreadable tag -- flags the request and the inventory record M3 expected
to be there, dings the station's discrepancy_rate, and suggests the next
place to look.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session

from app.adapters.m3_adapter import get_m3_adapter
from app.adapters.verify_tag import ExtractedTag, get_tag_verify_adapter
from app.models import InventoryCondition, InventoryItem, PartRequest, PartRequestStatus, Station
from app.planner.confidence import bump_station_discrepancy_rate, refresh_confidence


class PartRequestAlreadyResolved(Exception):
    """The request was already picked/issued/flagged -- a photo only resolves it once."""


def _describe_pick_mismatch(request: PartRequest, extracted: ExtractedTag) -> str:
    if extracted.part_number is None and extracted.serial is None:
        return f"nothing readable at {request.expected_location or 'the expected location'} -- shelf looks empty"
    return (
        f"tag at {request.expected_location or 'the expected location'} shows part "
        f"{extracted.part_number or 'unreadable'}, serial {extracted.serial or 'unreadable'} -- "
        f"expected part {request.part_number}"
    )


def _suggest_next_source(session: Session, request: PartRequest) -> str:
    adapter = get_m3_adapter()
    same_station = [
        r
        for r in adapter.get_expected_stock(session, request.part_number, request.station)
        if r.serial != request.expected_serial and r.condition == InventoryCondition.serviceable and not r.phantom_flag
    ]
    if same_station:
        return f"try {same_station[0].location or 'another location'} at {request.station}"

    elsewhere = [
        r
        for r in adapter.list_stock(session, part_number=request.part_number)
        if r.station != request.station and r.condition == InventoryCondition.serviceable and not r.phantom_flag
    ]
    if elsewhere:
        return f"try {elsewhere[0].station} ({elsewhere[0].location or 'location unknown'})"

    return "no other known stock -- consider raising a request"


def resolve_pick(session: Session, request: PartRequest, photo_filename: str, now: datetime) -> PartRequest:
    if request.status != PartRequestStatus.open:
        raise PartRequestAlreadyResolved(f"part request {request.id} is already {request.status.value}")

    extracted = get_tag_verify_adapter().read_tag(photo_filename)
    request.photo_filename = photo_filename
    request.picked_at = now

    adapter = get_m3_adapter()
    match = None
    if extracted.part_number:
        candidates = adapter.get_expected_stock(session, request.part_number, request.station)
        match = next(
            (c for c in candidates if c.part_number == extracted.part_number and c.serial == extracted.serial), None
        )

    if match:
        adapter.complete_issue(session, request, match.location, match.serial, now)
        item = session.get(InventoryItem, match.serial)
        if item:
            item.last_verified_at = now
            item.verified_by = request.mechanic
            item.phantom_flag = False
            refresh_confidence(session, item, now)
            session.add(item)
            session.commit()
    else:
        request.status = PartRequestStatus.flagged
        request.flagged_reason = _describe_pick_mismatch(request, extracted)

        if request.expected_serial:
            expected_item = session.get(InventoryItem, request.expected_serial)
            if expected_item:
                expected_item.phantom_flag = True
                refresh_confidence(session, expected_item, now)
                session.add(expected_item)

        station = session.get(Station, request.station)
        if station:
            bump_station_discrepancy_rate(session, station)

        request.suggested_next = _suggest_next_source(session, request)
        session.add(request)
        session.commit()

    session.refresh(request)
    return request
