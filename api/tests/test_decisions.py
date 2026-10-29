"""Covers the two human-decision paths: approving a plan (including picking
up a flight-change's staged recommendation), and overriding the system's
pick with a different feasible option plus a reason.
"""

from datetime import timedelta

import pytest
from sqlmodel import select

from app.models import Flight, FlightStatus, OverrideReason, Plan, PlanEvent, PlanOption, PlanStatus
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


def test_approving_a_comat_plan_books_cargo_and_a_shipping_ticket(session, hero_part):
    plan = _hero_plan(session, hero_part, PlanStatus.proposed)
    assert plan.option == PlanOption.comat  # the hero fixture's winning option

    approve_plan(session, plan)

    events = session.exec(select(PlanEvent).where(PlanEvent.plan_id == plan.id)).all()
    shipped = [e for e in events if e.event_type.value == "shipped"]
    assert len(shipped) == 1
    assert "iCargo booking confirmed" in shipped[0].detail
    assert "EV2301" in shipped[0].detail
    assert "shipping ticket" in shipped[0].detail
    assert "work order" in shipped[0].detail
    # the hero part is seeded as dangerous goods
    assert "DANGEROUS GOODS" in shipped[0].detail


def test_approving_a_non_comat_plan_still_gets_a_shipping_ticket_but_no_booking(session, hero_part):
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
    )
    assert result.option == PlanOption.buy

    events = session.exec(select(PlanEvent).where(PlanEvent.plan_id == plan.id)).all()
    shipped = [e for e in events if e.event_type.value == "shipped"]
    assert len(shipped) == 1
    assert "shipping ticket" in shipped[0].detail
    assert "work order" in shipped[0].detail
    assert "iCargo booking" not in shipped[0].detail


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
