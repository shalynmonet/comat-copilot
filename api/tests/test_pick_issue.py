"""Covers pick_issue.py: a photo that matches M3's expected stock
completes the issue and raises the inventory record's confidence; a
mismatch -- or an empty shelf, which reads back the same unreadable
tag -- flags the request and the expected inventory record, dings the
station's discrepancy_rate, and suggests somewhere else to look.
"""

from datetime import date, datetime, timedelta

import pytest

from app.adapters import verify_tag
from app.adapters.m3_adapter import get_m3_adapter
from app.models import (
    Aircraft,
    InventoryCondition,
    InventoryItem,
    Part,
    PartRequestStatus,
    Station,
)
from app.planner.pick_issue import PartRequestAlreadyResolved, resolve_pick

NOW = datetime(2026, 11, 1, 8, 0)
TODAY = date(2026, 11, 1)


@pytest.fixture()
def pick_world(session):
    session.add_all(
        [
            Station(code="AUS", name="Austin", lat=30.2, lon=-97.7),
            Station(code="TUL", name="Tulsa", lat=36.2, lon=-95.9),
            Aircraft(tail_number="N509EV", type="E175", current_station="AUS", overnight_station="DFW"),
            Part(part_number="STARTER-GEN", description="Starter Generator", shelf_life_days=3650, weight_lb=65, unit_cost=5000),
        ]
    )
    session.add(
        InventoryItem(
            serial="INV-AUS-STARTER-GEN-1",
            part_number="STARTER-GEN",
            station="AUS",
            condition=InventoryCondition.serviceable,
            expires_on=TODAY + timedelta(days=400),
            last_counted_on=TODAY,
            location="BIN-AUS-07",
        )
    )
    session.commit()
    request = get_m3_adapter().create_part_request(session, "Mike (Line Maint)", "N509EV", "STARTER-GEN", 1, "AUS", NOW)
    return request


def test_match_completes_the_issue_and_raises_confidence(session, pick_world):
    request = pick_world
    resolved = resolve_pick(session, request, verify_tag.PICK_MATCH_FILENAME, NOW)

    assert resolved.status == PartRequestStatus.issued
    assert resolved.picked_serial == "INV-AUS-STARTER-GEN-1"
    assert resolved.picked_location == "BIN-AUS-07"
    assert resolved.issued_at == NOW

    item = session.get(InventoryItem, "INV-AUS-STARTER-GEN-1")
    assert item.last_verified_at == NOW
    assert item.verified_by == "Mike (Line Maint)"
    assert item.phantom_flag is False
    assert item.confidence == 1.0


def test_mismatch_flags_the_request_and_the_expected_inventory_record(session, pick_world):
    request = pick_world
    station_before = session.get(Station, "AUS")
    discrepancy_before = station_before.discrepancy_rate

    resolved = resolve_pick(session, request, verify_tag.PICK_MISMATCH_FILENAME, NOW)

    assert resolved.status == PartRequestStatus.flagged
    assert "HYD-PUMP-A" in resolved.flagged_reason
    assert resolved.picked_serial is None

    item = session.get(InventoryItem, "INV-AUS-STARTER-GEN-1")
    assert item.phantom_flag is True

    session.refresh(station_before)
    assert station_before.discrepancy_rate > discrepancy_before


def test_mismatch_suggests_another_station_with_stock(session, pick_world):
    request = pick_world
    session.add(
        InventoryItem(
            serial="INV-TUL-STARTER-GEN-1",
            part_number="STARTER-GEN",
            station="TUL",
            condition=InventoryCondition.serviceable,
            expires_on=TODAY + timedelta(days=400),
            last_counted_on=TODAY,
            location="BIN-TUL-02",
        )
    )
    session.commit()

    resolved = resolve_pick(session, request, verify_tag.PICK_MISMATCH_FILENAME, NOW)

    assert resolved.suggested_next is not None
    assert "TUL" in resolved.suggested_next


def test_empty_location_is_treated_as_a_mismatch(session, pick_world):
    request = pick_world
    # An unrecognized filename reads back as fully unreadable -- the
    # same as an empty shelf.
    resolved = resolve_pick(session, request, "not-a-seeded-image.jpg", NOW)

    assert resolved.status == PartRequestStatus.flagged
    assert "empty" in resolved.flagged_reason

    item = session.get(InventoryItem, "INV-AUS-STARTER-GEN-1")
    assert item.phantom_flag is True


def test_resolving_an_already_resolved_request_raises(session, pick_world):
    request = pick_world
    resolve_pick(session, request, verify_tag.PICK_MATCH_FILENAME, NOW)

    with pytest.raises(PartRequestAlreadyResolved):
        resolve_pick(session, request, verify_tag.PICK_MATCH_FILENAME, NOW)
