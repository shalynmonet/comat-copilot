"""Covers M3's Expiring Lot Report flow: candidates.py excludes a spare
that would expire before it arrives, get_expected_stock prefers the
soonest-expiring lot, and expiring_lots.py recommends and carries out
each of the three actions (use / move / replace).
"""

from datetime import date, datetime, time, timedelta

import pytest
from sqlmodel import select

from app.adapters.m3_adapter import get_m3_adapter
from app.models import (
    Aircraft,
    ExpiringLotActionType,
    Flight,
    FlightStatus,
    InstalledPart,
    InventoryCondition,
    InventoryItem,
    Part,
    Plan,
    PlanOption,
    Priority,
    RaisedBy,
    ShippingRequest,
    ShippingRequestStatus,
    Station,
)
from app.planner.candidates import build_candidates
from app.planner.expiring_lots import approve_lot_action, scan_expiring_lots

TODAY = date(2026, 11, 1)
NOW = datetime(2026, 11, 1, 8, 0)


@pytest.fixture()
def lots_world(session):
    session.add_all(
        [
            Station(code="DFW", name="Dallas-Fort Worth", lat=32.9, lon=-97.0, has_maintenance=True),
            Station(code="CVG", name="Cincinnati", lat=39.0, lon=-84.7),
            Station(code="ORD", name="Chicago", lat=41.97, lon=-87.9),
            Aircraft(tail_number="N900EV", type="E175", current_station="DFW", overnight_station="CVG"),
            Part(part_number="WIDGET", description="Test Widget", shelf_life_days=365, weight_lb=10, unit_cost=250.0),
            InstalledPart(
                serial="SN-W1", part_number="WIDGET", tail_number="N900EV", position="P1",
                installed_on=TODAY, expires_on=TODAY + timedelta(days=5),
            ),
        ]
    )
    session.commit()
    return session


def test_spare_expiring_before_arrival_is_excluded(session, lots_world):
    session.add_all(
        [
            Flight(
                flight_number="EV1", tail_number="N901", origin="DFW", dest="CVG",
                sched_dep=NOW + timedelta(hours=2), sched_arr=NOW + timedelta(hours=4),
                status=FlightStatus.scheduled, cargo_capacity_lb=1000,
            ),
            InventoryItem(
                serial="INV-STALE", part_number="WIDGET", station="DFW", condition=InventoryCondition.serviceable,
                expires_on=TODAY - timedelta(days=1), last_counted_on=TODAY,  # already expired
            ),
            InventoryItem(
                serial="INV-FRESH", part_number="WIDGET", station="DFW", condition=InventoryCondition.serviceable,
                expires_on=TODAY + timedelta(days=30), last_counted_on=TODAY,
            ),
        ]
    )
    session.commit()

    installed = session.get(InstalledPart, "SN-W1")
    candidates = build_candidates(session, installed, now=NOW, include_disqualified=True)

    stale = next(c for c in candidates if c.spare_serial == "INV-STALE")
    fresh = next(c for c in candidates if c.spare_serial == "INV-FRESH")
    assert stale.disqualified
    assert "expires" in stale.disqualified_reason
    assert not fresh.disqualified


def test_get_expected_stock_prefers_the_soonest_expiring_lot(session, lots_world):
    session.add_all(
        [
            InventoryItem(
                serial="INV-LATER", part_number="WIDGET", station="DFW", condition=InventoryCondition.serviceable,
                expires_on=TODAY + timedelta(days=60), last_counted_on=TODAY,
            ),
            InventoryItem(
                serial="INV-SOONER", part_number="WIDGET", station="DFW", condition=InventoryCondition.serviceable,
                expires_on=TODAY + timedelta(days=10), last_counted_on=TODAY,
            ),
        ]
    )
    session.commit()

    stock = get_m3_adapter().get_expected_stock(session, "WIDGET", "DFW")
    assert stock[0].serial == "INV-SOONER"


def test_scan_recommends_use_when_the_same_station_has_a_known_need(session, lots_world):
    session.add_all(
        [
            InventoryItem(
                serial="INV-LOT-USE", part_number="WIDGET", station="DFW", condition=InventoryCondition.serviceable,
                expires_on=TODAY + timedelta(days=5), last_counted_on=TODAY, lot="LOT-USE",
            ),
            ShippingRequest(
                part_number="WIDGET", serial="SN-W1", station_needed="DFW", needed_by=TODAY + timedelta(days=4),
                priority=Priority.std, raised_by=RaisedBy.maintenance_control, status=ShippingRequestStatus.open,
            ),
        ]
    )
    session.commit()

    actions = scan_expiring_lots(session, window_days=30, now=NOW)
    action = next(a for a in actions if a.inventory_serial == "INV-LOT-USE")
    assert action.action == ExpiringLotActionType.use


def test_scan_recommends_move_and_approving_builds_a_real_transfer_plan(session, lots_world):
    session.add(
        InventoryItem(
            serial="INV-LOT-MOVE", part_number="WIDGET", station="ORD", condition=InventoryCondition.serviceable,
            expires_on=TODAY + timedelta(days=5), last_counted_on=TODAY, lot="LOT-MOVE",
        )
    )
    session.commit()
    # SN-W1 (installed on N900EV, overnighting at CVG) needs WIDGET by day 4 --
    # before the ORD lot expires on day 5.
    session.add(
        ShippingRequest(
            part_number="WIDGET", serial="SN-W1", station_needed="CVG", needed_by=TODAY + timedelta(days=4),
            priority=Priority.std, raised_by=RaisedBy.maintenance_control, status=ShippingRequestStatus.open,
        )
    )
    session.commit()

    actions = scan_expiring_lots(session, window_days=30, now=NOW)
    action = next(a for a in actions if a.inventory_serial == "INV-LOT-MOVE")
    assert action.action == ExpiringLotActionType.move

    approved = approve_lot_action(session, action, now=NOW)
    assert approved.plan_id is not None
    plan = session.get(Plan, approved.plan_id)
    assert plan.option in (PlanOption.comat, PlanOption.transfer)
    assert plan.installed_serial == "SN-W1"


def test_scan_recommends_replace_and_raises_a_request_when_no_spare_remains(session, lots_world):
    session.add(
        InventoryItem(
            serial="INV-LOT-REPLACE", part_number="WIDGET", station="ORD", condition=InventoryCondition.serviceable,
            expires_on=TODAY + timedelta(days=5), last_counted_on=TODAY, lot="LOT-REPLACE",
        )
    )
    session.commit()

    actions = scan_expiring_lots(session, window_days=30, now=NOW)
    action = next(a for a in actions if a.inventory_serial == "INV-LOT-REPLACE")
    assert action.action == ExpiringLotActionType.replace
    assert "no other valid spare" in action.reason

    raised = session.exec(
        select(ShippingRequest).where(
            ShippingRequest.part_number == "WIDGET", ShippingRequest.raised_by == RaisedBy.copilot
        )
    ).first()
    assert raised is not None
    assert raised.serial is None
    assert raised.station_needed == "ORD"


def test_scan_recommends_replace_without_raising_a_request_when_another_spare_remains(session, lots_world):
    session.add_all(
        [
            InventoryItem(
                serial="INV-LOT-REPLACE2", part_number="WIDGET", station="ORD", condition=InventoryCondition.serviceable,
                expires_on=TODAY + timedelta(days=5), last_counted_on=TODAY, lot="LOT-REPLACE2",
            ),
            InventoryItem(
                serial="INV-ORD-BACKUP", part_number="WIDGET", station="ORD", condition=InventoryCondition.serviceable,
                expires_on=TODAY + timedelta(days=200), last_counted_on=TODAY,
            ),
        ]
    )
    session.commit()

    actions = scan_expiring_lots(session, window_days=30, now=NOW)
    action = next(a for a in actions if a.inventory_serial == "INV-LOT-REPLACE2")
    assert action.action == ExpiringLotActionType.replace
    assert "another valid spare remains" in action.reason

    raised = session.exec(
        select(ShippingRequest).where(
            ShippingRequest.part_number == "WIDGET", ShippingRequest.raised_by == RaisedBy.copilot
        )
    ).first()
    assert raised is None
