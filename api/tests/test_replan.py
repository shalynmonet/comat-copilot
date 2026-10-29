"""Covers re-planning on a flight delay.

A plan that was never approved keeps the old behavior: the system just
recalculates and updates it directly. A plan a human already *approved* is
handled more carefully -- the flight change flags it at_risk and stages the
new recommendation in pending_* rather than silently rewriting the
committed option, requiring a fresh approval (covered in test_decisions.py).
"""

from datetime import timedelta

from sqlmodel import select

from app.models import Flight, FlightStatus, Plan, PlanEvent, PlanOption, PlanStatus
from app.planner.candidates import build_candidates
from app.planner.score import pick_best, to_plan
from app.planner.replan import replan_for_flight
from tests.conftest import DEADLINE, NOW


def _hero_plan(session, hero_part, status: PlanStatus) -> Plan:
    candidates = build_candidates(session, hero_part, now=NOW)
    best = pick_best(candidates, deadline=DEADLINE)
    plan = to_plan(hero_part.serial, best, status=status)
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


def _get_hero_flight(session) -> Flight:
    return session.exec(select(Flight).where(Flight.flight_number == "EV2301")).one()


def _delay_hero_flight(session, hours: int) -> Flight:
    flight = _get_hero_flight(session)
    flight.status = FlightStatus.delayed
    flight.sched_dep += timedelta(hours=hours)
    flight.sched_arr += timedelta(hours=hours)
    session.add(flight)
    session.commit()
    session.refresh(flight)
    return flight


def test_proposed_plan_still_auto_updates_on_a_big_delay(session, hero_part):
    plan = _hero_plan(session, hero_part, PlanStatus.proposed)
    flight = _delay_hero_flight(session, 10)

    touched = replan_for_flight(session, flight, now=NOW)

    assert len(touched) == 1
    updated = touched[0]
    assert updated.id == plan.id
    assert updated.option == PlanOption.transfer
    assert updated.flight_number is None
    assert updated.status == PlanStatus.re_routed
    assert updated.pending_option is None  # no approval gate for an unapproved plan


def test_small_delay_on_approved_plan_flags_at_risk_without_changing_the_committed_option(session, hero_part):
    plan = _hero_plan(session, hero_part, PlanStatus.approved)
    flight = _delay_hero_flight(session, 3)

    touched = replan_for_flight(session, flight, now=NOW)

    assert len(touched) == 1
    result = touched[0]
    assert result.id == plan.id
    assert result.status == PlanStatus.at_risk
    # the committed option is untouched -- still what the human approved
    assert result.option == PlanOption.comat
    assert result.flight_number == "EV2301"
    # the (possibly-unchanged) recommendation is staged, not applied
    assert result.pending_option == PlanOption.comat
    assert result.pending_source == "DFW"
    assert result.pending_flight_number == "EV2301"


def test_big_delay_on_approved_plan_stages_transfer_without_applying_it(session, hero_part):
    plan = _hero_plan(session, hero_part, PlanStatus.approved)
    flight = _delay_hero_flight(session, 10)

    touched = replan_for_flight(session, flight, now=NOW)

    assert len(touched) == 1
    result = touched[0]
    assert result.id == plan.id
    assert result.status == PlanStatus.at_risk
    # still the stale, originally-approved COMAT option -- not silently switched
    assert result.option == PlanOption.comat
    assert result.flight_number == "EV2301"
    # the new recommendation is staged for approval, not applied
    assert result.pending_option == PlanOption.transfer
    assert result.pending_source == "DFW"
    assert result.pending_flight_number is None
    assert result.pending_reason


def test_reroute_is_logged_as_a_plan_event(session, hero_part):
    plan = _hero_plan(session, hero_part, PlanStatus.approved)
    flight = _delay_hero_flight(session, 10)

    replan_for_flight(session, flight, now=NOW)

    events = session.exec(select(PlanEvent).where(PlanEvent.plan_id == plan.id)).all()
    assert len(events) == 1
    assert events[0].event_type.value == "re-routed"
    assert "EV2301" in events[0].detail


def test_shipped_plans_are_not_replanned(session, hero_part):
    plan = _hero_plan(session, hero_part, PlanStatus.approved)
    plan.status = PlanStatus.shipped
    session.add(plan)
    session.commit()

    flight = _delay_hero_flight(session, 10)

    touched = replan_for_flight(session, flight, now=NOW)

    assert touched == []
    session.refresh(plan)
    assert plan.status == PlanStatus.shipped
    assert plan.option == PlanOption.comat  # untouched
