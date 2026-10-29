"""Covers the two human-decision paths: approving a plan (including picking
up a flight-change's staged recommendation), and overriding the system's
pick with a different feasible option plus a reason. Both paths also
build and save a SAFE-ready shipment draft -- never submitted by Copilot
itself, just prepared for Stores to review.
"""

from datetime import timedelta

import pytest
from sqlmodel import select

from app.models import (
    CommodityProfile,
    Flight,
    FlightStatus,
    HandoffRoute,
    OverrideReason,
    Plan,
    PlanEvent,
    PlanOption,
    PlanStatus,
    Priority,
    ShipmentDraft,
    ShipmentDraftStatus,
)
from app.planner.candidates import build_candidates
from app.planner.decisions import NoSuchCandidate, approve_plan, choose_alternative
from app.planner.replan import replan_for_flight
from app.planner.score import pick_best, to_plan
from tests.conftest import DEADLINE, NOW


def _hero_plan(session, hero_part, status: PlanStatus) -> Plan:
    candidates = build_candidates(session, hero_part, now=NOW)
    best = pick_best(candidates, deadline=DEADLINE)
    plan = to_plan(hero_part.serial, best, status=status)
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


def test_approve_on_a_plain_proposed_plan_just_flips_status(session, hero_part):
    plan = _hero_plan(session, hero_part, PlanStatus.proposed)

    result = approve_plan(session, plan)

    assert result.status == PlanStatus.approved
    assert result.option == PlanOption.comat  # unchanged, nothing was pending


def test_approving_the_hero_plan_builds_a_ready_draft_with_mrd_priority(session, hero_part):
    plan = _hero_plan(session, hero_part, PlanStatus.proposed)
    assert plan.option == PlanOption.comat  # the hero fixture's winning option

    result = approve_plan(session, plan, now=NOW)

    # only one DFW->CVG flight exists in the fixture -- it's the last
    # viable one, so Must Ride, not Standard.
    assert result.priority == Priority.mrd
    assert result.commodity_profile == CommodityProfile.critical_planeside
    assert result.handoff_route == HandoffRoute.plane_side
    assert result.handling_codes == ["AOG"]  # EZP is added on save, not here

    draft = session.exec(select(ShipmentDraft).where(ShipmentDraft.plan_id == plan.id)).one()
    assert draft.status == ShipmentDraftStatus.ready
    assert draft.missing_fields == []
    assert draft.fields["part_number"] == "OXY-BTL-02"
    assert draft.fields["is_dangerous_goods"] is True
    assert draft.fields["agent_pal"] == "PAL-DFW-01"
    assert draft.fields["consignee_pal"] == "PAL-CVG-01"
    assert draft.fields["flight_legs"] == ["EV2301"]

    events = session.exec(select(PlanEvent).where(PlanEvent.plan_id == plan.id)).all()
    draft_events = [e for e in events if e.event_type.value == "draft-created"]
    assert len(draft_events) == 1
    assert "ready" in draft_events[0].detail


def test_a_buy_plan_has_no_station_pals_and_stays_in_draft_status(session, hero_part):
    plan = _hero_plan(session, hero_part, PlanStatus.proposed)

    result = choose_alternative(
        session,
        plan,
        hero_part,
        option=PlanOption.buy,
        source="AeroSource",
        flight_number=None,
        reason=OverrideReason.preferred_vendor,
        note=None,
        now=NOW,
    )
    assert result.option == PlanOption.buy

    draft = session.exec(select(ShipmentDraft).where(ShipmentDraft.plan_id == plan.id)).one()
    # a vendor isn't one of our stations, so there's no PAL to fill --
    # correctly keeps the draft at "draft" rather than faking a value.
    assert draft.status == ShipmentDraftStatus.draft
    assert "agent_pal" in draft.missing_fields
    assert "shipper_pal" in draft.missing_fields
    assert draft.fields["origin_station"] == "AeroSource"
    assert draft.fields["condition"] == "new"

    events = session.exec(select(PlanEvent).where(PlanEvent.plan_id == plan.id)).all()
    draft_events = [e for e in events if e.event_type.value == "draft-created"]
    assert len(draft_events) == 1
    assert "missing" in draft_events[0].detail


def test_approve_adopts_a_pending_recommendation(session, hero_part):
    plan = _hero_plan(session, hero_part, PlanStatus.approved)
    flight = session.exec(select(Flight).where(Flight.flight_number == "EV2301")).one()
    flight.status = FlightStatus.delayed
    flight.sched_dep += timedelta(hours=10)
    flight.sched_arr += timedelta(hours=10)
    session.add(flight)
    session.commit()
    session.refresh(flight)

    replan_for_flight(session, flight, now=NOW)
    session.refresh(plan)
    assert plan.status == PlanStatus.at_risk
    assert plan.pending_option == PlanOption.transfer

    result = approve_plan(session, plan)

    assert result.status == PlanStatus.approved
    assert result.option == PlanOption.transfer
    assert result.flight_number is None
    assert result.pending_option is None  # cleared after being adopted

    events = session.exec(select(PlanEvent).where(PlanEvent.plan_id == plan.id)).all()
    assert any(e.event_type.value == "approved" for e in events)


def test_choose_alternative_applies_the_picked_candidate_and_logs_why(session, hero_part):
    plan = _hero_plan(session, hero_part, PlanStatus.proposed)

    result = choose_alternative(
        session,
        plan,
        hero_part,
        option=PlanOption.transfer,
        source="DFW",
        flight_number=None,
        reason=OverrideReason.spare_needed_elsewhere,
        note=None,
    )

    assert result.option == PlanOption.transfer
    assert result.source == "DFW"
    assert result.status == PlanStatus.approved
    assert "spare needed elsewhere" in result.reason

    events = session.exec(select(PlanEvent).where(PlanEvent.plan_id == plan.id)).all()
    assert any(e.event_type.value == "overridden" for e in events)
    assert any("spare needed elsewhere" in (e.detail or "") for e in events)


def test_choose_alternative_other_reason_uses_the_free_text_note(session, hero_part):
    plan = _hero_plan(session, hero_part, PlanStatus.proposed)

    result = choose_alternative(
        session,
        plan,
        hero_part,
        option=PlanOption.buy,
        source="AeroSource",
        flight_number=None,
        reason=OverrideReason.other,
        note="customer VIP on this tail, want the fastest option",
    )

    assert result.option == PlanOption.buy
    assert "customer VIP" in result.reason


def test_choose_alternative_rejects_a_disqualified_or_nonexistent_option(session, hero_part):
    plan = _hero_plan(session, hero_part, PlanStatus.proposed)

    with pytest.raises(NoSuchCandidate):
        choose_alternative(
            session,
            plan,
            hero_part,
            option=PlanOption.comat,
            source="ORD",  # unserviceable spare -- never a feasible candidate
            flight_number=None,
            reason=OverrideReason.other,
            note="test",
        )
