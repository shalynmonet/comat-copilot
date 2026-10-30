"""Covers failures.py: a failure write-up immediately creates a request
and a real plan, a low-confidence spare is skipped in favor of the next
valid one when there's no time to verify before its flight's booking
cutoff (and still gated normally -- a verify_task -- when there is), and
the failure-response-time stat.
"""

from datetime import date, datetime, timedelta

import pytest
from sqlmodel import select

from app.models import (
    Aircraft,
    Flight,
    FlightStatus,
    InstalledPart,
    InventoryCondition,
    InventoryItem,
    Part,
    PlanOption,
    PlanStatus,
    RaisedBy,
    RemovalHistory,
    ShipmentDraft,
    ShipmentDraftStatus,
    ShippingRequestTrigger,
    Station,
    VendorQuote,
)
from app.planner.failures import (
    NoInstalledPartForFailure,
    compute_failure_response_time_median_minutes,
    report_failure,
)

TODAY = date(2026, 11, 1)
NOW = datetime(2026, 11, 1, 8, 0)


@pytest.fixture()
def failure_world(session):
    session.add_all(
        [
            Station(code="DFW", name="Dallas-Fort Worth", lat=32.9, lon=-97.0, has_maintenance=True, discrepancy_rate=0.3),
            Station(code="ORD", name="Chicago", lat=41.97, lon=-87.9),
            Station(code="CVG", name="Cincinnati", lat=39.0, lon=-84.7),
            Aircraft(tail_number="N900", type="E175", current_station="CVG", overnight_station="CVG"),
            Part(part_number="WIDGET", description="Test Widget", shelf_life_days=3650, weight_lb=10, unit_cost=400.0),
            InstalledPart(
                serial="SN-N900-WIDGET", part_number="WIDGET", tail_number="N900", position="P1",
                installed_on=TODAY, expires_on=TODAY + timedelta(days=365),
            ),
            # A buy fallback so there's always a feasible (confidence-free) option.
            VendorQuote(
                vendor="AeroSource", part_number="WIDGET", price=500.0, lead_time_hrs=20.0,
                ship_to_station="CVG", certs="FAA 8130-3",
            ),
        ]
    )
    session.commit()
    return session


def test_failure_creates_a_request_and_an_immediate_plan(session, failure_world):
    session.add(
        InventoryItem(
            serial="INV-ORD-WIDGET-1", part_number="WIDGET", station="ORD", condition=InventoryCondition.serviceable,
            expires_on=TODAY + timedelta(days=400), last_counted_on=TODAY,
            last_verified_at=NOW, verified_by="Stores",  # confident
        )
    )
    session.commit()

    request, plan = report_failure(session, "N900", "CVG", "WIDGET", RaisedBy.maintenance_control, "burning smell", NOW)

    assert request.trigger == ShippingRequestTrigger.failure
    assert request.plan_id is not None
    assert plan is not None
    assert plan.installed_serial == "SN-N900-WIDGET"
    assert plan.status in (PlanStatus.approved, PlanStatus.pending_verification)


def test_failure_for_an_untracked_part_raises(session, failure_world):
    with pytest.raises(NoInstalledPartForFailure):
        report_failure(session, "N900", "CVG", "NOT-A-REAL-PART", RaisedBy.stores, None, NOW)


def test_low_confidence_spare_is_skipped_when_no_time_to_verify_before_cutoff(session, failure_world):
    # DFW spare is low-confidence (never verified, heavy moves, DFW has a
    # discrepancy history) and its flight departs soon enough that the
    # cutoff leaves no real time for a photo verify.
    session.add_all(
        [
            InventoryItem(
                serial="INV-DFW-WIDGET-LOW", part_number="WIDGET", station="DFW",
                condition=InventoryCondition.serviceable, expires_on=TODAY + timedelta(days=400),
                last_counted_on=TODAY, move_count_30d=5,
            ),
            Flight(
                flight_number="EV1", tail_number="N901", origin="DFW", dest="CVG",
                sched_dep=NOW + timedelta(minutes=70), sched_arr=NOW + timedelta(hours=3),
                status=FlightStatus.scheduled, cargo_capacity_lb=1000,
            ),
        ]
    )
    session.commit()

    request, plan = report_failure(session, "N900", "CVG", "WIDGET", RaisedBy.maintenance_control, None, NOW)

    assert plan is not None
    assert "skipped DFW" in plan.reason
    # DFW was skipped -- the buy fallback (no confidence dependency) won instead.
    assert plan.option == PlanOption.buy
    assert plan.status == PlanStatus.approved


def test_low_confidence_spare_still_gates_normally_when_there_is_time(session, failure_world):
    session.add_all(
        [
            InventoryItem(
                serial="INV-DFW-WIDGET-LOW2", part_number="WIDGET", station="DFW",
                condition=InventoryCondition.serviceable, expires_on=TODAY + timedelta(days=400),
                last_counted_on=TODAY, move_count_30d=5,
            ),
            Flight(
                flight_number="EV2", tail_number="N902", origin="DFW", dest="CVG",
                sched_dep=NOW + timedelta(hours=5), sched_arr=NOW + timedelta(hours=7),
                status=FlightStatus.scheduled, cargo_capacity_lb=1000,
            ),
        ]
    )
    session.commit()

    request, plan = report_failure(session, "N900", "CVG", "WIDGET", RaisedBy.maintenance_control, None, NOW)

    assert plan is not None
    assert "skipped" not in plan.reason
    assert plan.status == PlanStatus.pending_verification
    assert plan.option == PlanOption.comat


def test_failure_response_time_is_the_median_of_completed_cases(session, failure_world):
    session.add(
        InventoryItem(
            serial="INV-ORD-WIDGET-2", part_number="WIDGET", station="ORD", condition=InventoryCondition.serviceable,
            expires_on=TODAY + timedelta(days=400), last_counted_on=TODAY,
            last_verified_at=NOW, verified_by="Stores",
        )
    )
    session.commit()

    assert compute_failure_response_time_median_minutes(session) is None

    request, plan = report_failure(session, "N900", "CVG", "WIDGET", RaisedBy.maintenance_control, None, NOW)
    draft = session.exec(select(ShipmentDraft).where(ShipmentDraft.plan_id == plan.id)).one()
    draft.status = ShipmentDraftStatus.submitted
    draft.updated_at = NOW + timedelta(minutes=12)
    session.add(draft)
    session.commit()

    median = compute_failure_response_time_median_minutes(session)
    assert median == pytest.approx(12.0)


def test_failure_logs_removal_history(session, failure_world):
    session.add(
        InventoryItem(
            serial="INV-ORD-WIDGET-3", part_number="WIDGET", station="ORD", condition=InventoryCondition.serviceable,
            expires_on=TODAY + timedelta(days=400), last_counted_on=TODAY,
            last_verified_at=NOW, verified_by="Stores",
        )
    )
    session.commit()

    report_failure(session, "N900", "CVG", "WIDGET", RaisedBy.maintenance_control, "test", NOW)

    history = session.exec(select(RemovalHistory).where(RemovalHistory.tail_number == "N900")).all()
    assert len(history) == 1
    assert history[0].part_number == "WIDGET"
    assert history[0].fleet_type == "E175"
    assert history[0].reason.value == "failure"
