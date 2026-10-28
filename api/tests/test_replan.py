"""Covers re-planning on a flight delay: a small delay leaves an
already-approved plan untouched, a bigger one reroutes it to the ground
transfer, the switch is logged as a plan event, and plans that are no
longer "active" (shipped, cancelled) are left alone.
"""

from datetime import timedelta

from sqlmodel import select

from app.models import Flight, FlightStatus, Plan, PlanEvent, PlanOption, PlanStatus
from app.planner.candidates import build_candidates
from app.planner.score import pick_best, to_plan
from app.planner.replan import replan_for_flight
from tests.conftest import DEADLINE, NOW


def _approve_hero_plan(session, hero_part) -> Plan:
    candidates = build_candidates(session, hero_part, now=NOW)
    best = pick_best(candidates, deadline=DEADLINE)
    plan = to_plan(hero_part.serial, best, status=PlanStatus.approved)
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


def _get_hero_flight(session) -> Flight:
    return session.exec(select(Flight).where(Flight.flight_number == "EV2301")).one()


def test_small_delay_leaves_a_comfortable_plan_untouched(session, hero_part):
    plan = _approve_hero_plan(session, hero_part)
    flight = _get_hero_flight(session)

    flight.status = FlightStatus.delayed
    flight.sched_dep += timedelta(hours=3)
    flight.sched_arr += timedelta(hours=3)
    session.add(flight)
    session.commit()
    session.refresh(flight)

    touched = replan_for_flight(session, flight, now=NOW)

    assert len(touched) == 1
    assert touched[0].id == plan.id
    assert touched[0].option == PlanOption.comat
    assert touched[0].flight_number == "EV2301"
    assert touched[0].status == PlanStatus.approved  # unchanged


def test_big_delay_reroutes_to_ground_transfer(session, hero_part):
    plan = _approve_hero_plan(session, hero_part)
    flight = _get_hero_flight(session)

    flight.status = FlightStatus.delayed
    flight.sched_dep += timedelta(hours=10)
    flight.sched_arr += timedelta(hours=10)
    session.add(flight)
    session.commit()
    session.refresh(flight)

    touched = replan_for_flight(session, flight, now=NOW)

    assert len(touched) == 1
    rerouted = touched[0]
    assert rerouted.id == plan.id
    assert rerouted.option == PlanOption.transfer
    assert rerouted.flight_number is None
    assert rerouted.source == "DFW"
    assert rerouted.status == PlanStatus.re_routed


def test_reroute_is_logged_as_a_plan_event(session, hero_part):
    plan = _approve_hero_plan(session, hero_part)
    flight = _get_hero_flight(session)
    flight.sched_arr += timedelta(hours=10)
    session.add(flight)
    session.commit()
    session.refresh(flight)

    replan_for_flight(session, flight, now=NOW)

    events = session.exec(select(PlanEvent).where(PlanEvent.plan_id == plan.id)).all()
    assert len(events) == 1
    assert events[0].event_type.value == "re-routed"
    assert "EV2301" in events[0].detail


def test_shipped_plans_are_not_replanned(session, hero_part):
    plan = _approve_hero_plan(session, hero_part)
    plan.status = PlanStatus.shipped
    session.add(plan)
    session.commit()

    flight = _get_hero_flight(session)
    flight.sched_arr += timedelta(hours=10)
    session.add(flight)
    session.commit()
    session.refresh(flight)

    touched = replan_for_flight(session, flight, now=NOW)

    assert touched == []
    session.refresh(plan)
    assert plan.status == PlanStatus.shipped
    assert plan.option == PlanOption.comat  # untouched
