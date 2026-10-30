"""Covers stocking.py: failure counts per (part, fleet type) below the
threshold raise nothing, enough failures raise a suggestion for every
operating station that lacks a spare (and none for one that has it),
and approving a suggestion raises a station-level STD request.
"""

from datetime import date, timedelta

import pytest

from app.models import (
    Aircraft,
    InventoryCondition,
    InventoryItem,
    Part,
    RemovalHistory,
    RemovalReason,
    ShippingRequestStatus,
    Station,
)
from app.planner.stocking import StockingSuggestionAlreadyResolved, approve_stocking_suggestion, scan_stocking_suggestions

TODAY = date(2026, 11, 1)


@pytest.fixture()
def stocking_world(session):
    session.add_all(
        [
            Station(code="DFW", name="Dallas-Fort Worth", lat=32.9, lon=-97.0),
            Station(code="ORD", name="Chicago", lat=41.97, lon=-87.9),
            Aircraft(tail_number="N1", type="CRJ900", current_station="DFW", overnight_station="ORD"),
            Aircraft(tail_number="N2", type="CRJ900", current_station="ORD", overnight_station="DFW"),
            Part(part_number="GADGET", description="Test Gadget", shelf_life_days=3650, weight_lb=5, unit_cost=300.0),
        ]
    )
    session.commit()
    return session


def test_below_threshold_raises_nothing(session, stocking_world):
    session.add(
        RemovalHistory(
            part_number="GADGET", fleet_type="CRJ900", station="DFW", tail_number="N1",
            removed_on=TODAY - timedelta(days=10), reason=RemovalReason.failure,
        )
    )
    session.commit()

    suggestions = scan_stocking_suggestions(session)
    assert suggestions == []


def test_enough_failures_suggests_stations_without_a_spare(session, stocking_world):
    for i in range(2):
        session.add(
            RemovalHistory(
                part_number="GADGET", fleet_type="CRJ900", station="DFW", tail_number="N1",
                removed_on=TODAY - timedelta(days=10 * i), reason=RemovalReason.failure,
            )
        )
    # ORD already holds a serviceable spare -- shouldn't get suggested.
    session.add(
        InventoryItem(
            serial="INV-ORD-GADGET-1", part_number="GADGET", station="ORD", condition=InventoryCondition.serviceable,
            expires_on=TODAY + timedelta(days=400), last_counted_on=TODAY,
        )
    )
    session.commit()

    suggestions = scan_stocking_suggestions(session)
    stations = {s.station for s in suggestions}
    assert "DFW" in stations
    assert "ORD" not in stations
    assert all(s.failure_count == 2 for s in suggestions)


def test_scan_is_idempotent(session, stocking_world):
    for i in range(2):
        session.add(
            RemovalHistory(
                part_number="GADGET", fleet_type="CRJ900", station="DFW", tail_number="N1",
                removed_on=TODAY - timedelta(days=10 * i), reason=RemovalReason.failure,
            )
        )
    session.commit()

    first = scan_stocking_suggestions(session)
    second = scan_stocking_suggestions(session)
    assert len(first) > 0
    assert second == []  # already-suggested pairs aren't duplicated


def test_approving_raises_an_std_request(session, stocking_world):
    for i in range(2):
        session.add(
            RemovalHistory(
                part_number="GADGET", fleet_type="CRJ900", station="DFW", tail_number="N1",
                removed_on=TODAY - timedelta(days=10 * i), reason=RemovalReason.failure,
            )
        )
    session.commit()

    suggestions = scan_stocking_suggestions(session)
    suggestion = next(s for s in suggestions if s.station == "DFW")

    approved = approve_stocking_suggestion(session, suggestion)

    assert approved.status.value == "approved"
    assert approved.request_id is not None

    from app.models import ShippingRequest

    request = session.get(ShippingRequest, approved.request_id)
    assert request.part_number == "GADGET"
    assert request.station_needed == "DFW"
    assert request.status == ShippingRequestStatus.open
    assert request.serial is None

    with pytest.raises(StockingSuggestionAlreadyResolved):
        approve_stocking_suggestion(session, suggestion)
