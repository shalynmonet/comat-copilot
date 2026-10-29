"""Covers intake.py: the expiry scan raises a copilot request for the
hero part (and not a duplicate on a second scan), suggest_for_part gives
the same source/flight/priority the planner would actually pick,
link_request_to_plan attaches a created plan to its open request, and
the avoided stats count a fulfilled STD/low_cargo request correctly.
"""

from sqlmodel import select

from app.models import (
    CommodityProfile,
    Plan,
    PlanOption,
    PlanStatus,
    Priority,
    RaisedBy,
    ShippingRequest,
    ShippingRequestStatus,
)
from app.planner.decisions import approve_plan
from app.planner.intake import (
    compute_avoided_stats,
    link_request_to_plan,
    raise_copilot_requests,
    suggest_for_part,
)
from app.planner.score import pick_best, to_plan
from app.planner.candidates import build_candidates
from tests.conftest import DEADLINE, NOW


def test_suggest_for_part_matches_what_the_planner_would_pick(session, hero_part):
    suggestion = suggest_for_part(session, hero_part, NOW)

    assert suggestion.option == PlanOption.comat
    assert suggestion.source == "DFW"
    assert suggestion.flight_number == "EV2301"
    assert suggestion.priority == Priority.mrd  # only one DFW->CVG flight in the fixture


def test_expiry_scan_raises_a_copilot_request_for_the_hero_part(session, hero_part):
    raised = raise_copilot_requests(session, window_days=7, now=NOW)

    assert len(raised) == 1
    request = raised[0]
    assert request.serial == hero_part.serial
    assert request.raised_by == RaisedBy.copilot
    assert request.status == ShippingRequestStatus.open
    assert request.priority == Priority.mrd
    assert request.station_needed == "CVG"


def test_a_second_scan_does_not_raise_a_duplicate(session, hero_part):
    first = raise_copilot_requests(session, window_days=7, now=NOW)
    second = raise_copilot_requests(session, window_days=7, now=NOW)

    assert len(first) == 1
    assert second == []
    all_requests = session.exec(select(ShippingRequest)).all()
    assert len(all_requests) == 1


def test_scan_skips_a_part_that_already_has_a_request_from_anyone(session, hero_part):
    session.add(
        ShippingRequest(
            part_number=hero_part.part_number,
            serial=hero_part.serial,
            station_needed="CVG",
            needed_by=hero_part.expires_on,
            priority=Priority.aog,
            raised_by=RaisedBy.maintenance_control,
            status=ShippingRequestStatus.open,
        )
    )
    session.commit()

    raised = raise_copilot_requests(session, window_days=7, now=NOW)

    assert raised == []  # maintenance control already raised it -- Copilot doesn't duplicate


def test_link_request_to_plan_attaches_an_open_request(session, hero_part):
    raise_copilot_requests(session, window_days=7, now=NOW)
    request = session.exec(select(ShippingRequest).where(ShippingRequest.serial == hero_part.serial)).one()
    assert request.plan_id is None

    candidates = build_candidates(session, hero_part, now=NOW)
    best = pick_best(candidates, deadline=DEADLINE)
    plan = to_plan(hero_part.serial, best, status=PlanStatus.proposed)
    session.add(plan)
    session.commit()
    session.refresh(plan)

    linked = link_request_to_plan(session, hero_part.serial, plan.id)
    session.commit()

    assert linked.id == request.id
    session.refresh(request)
    assert request.plan_id == plan.id
    assert request.status == ShippingRequestStatus.planned


def test_link_request_to_plan_is_a_no_op_without_an_open_request(session, hero_part):
    result = link_request_to_plan(session, hero_part.serial, plan_id=999)
    assert result is None


def test_avoided_stats_count_a_fulfilled_std_low_cargo_request(session, hero_part):
    raise_copilot_requests(session, window_days=7, now=NOW)
    request = session.exec(select(ShippingRequest).where(ShippingRequest.serial == hero_part.serial)).one()

    plan = Plan(
        installed_serial=hero_part.serial, option=PlanOption.buy, source="AeroSource", cost=930.0, risk_score=0.1,
        status=PlanStatus.shipped, priority=Priority.std, commodity_profile=CommodityProfile.low_cargo,
    )
    session.add(plan)
    session.commit()
    session.refresh(plan)

    request.plan_id = plan.id
    session.add(request)
    session.commit()

    stats = compute_avoided_stats(session)
    assert stats.aogs_avoided == 1
    assert stats.planeside_runs_avoided == 1


def test_avoided_stats_do_not_count_an_unfulfilled_or_non_std_request(session, hero_part):
    raise_copilot_requests(session, window_days=7, now=NOW)
    stats = compute_avoided_stats(session)
    # request exists but has no linked, shipped plan yet
    assert stats.aogs_avoided == 0
    assert stats.planeside_runs_avoided == 0
