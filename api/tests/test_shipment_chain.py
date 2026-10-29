"""Covers submit_shipment(): the full iCargo chain for a plane_side vs
to_cargo plan, the 7-vs-4 step tracker, the DG exemption note at
screening, refusing to submit a draft that isn't ready, and that every
status change is logged as its own plan_event.
"""

import pytest
from sqlmodel import select

from app.models import OverrideReason, PlanEvent, PlanOption, PlanStatus
from app.planner.candidates import build_candidates
from app.planner.decisions import approve_plan, choose_alternative
from app.planner.score import pick_best, to_plan
from app.planner.shipment_chain import DraftNotReady, NoDraftToSubmit, submit_shipment
from tests.conftest import DEADLINE, NOW


def _proposed_hero_plan(session, hero_part):
    candidates = build_candidates(session, hero_part, now=NOW)
    best = pick_best(candidates, deadline=DEADLINE)
    plan = to_plan(hero_part.serial, best, status=PlanStatus.proposed)
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


def _approved_hero_plan(session, hero_part):
    return approve_plan(session, _proposed_hero_plan(session, hero_part), now=NOW)


def test_plane_side_chain_runs_all_seven_steps_and_sets_the_awb(session, hero_part):
    plan = _approved_hero_plan(session, hero_part)
    assert plan.handoff_route.value == "plane_side"

    draft = submit_shipment(session, plan, now=NOW)

    assert draft.status.value == "submitted"
    assert plan.awb_number.startswith("DEMO-AWB-")
    assert plan.shipment_status.value == "delivered"  # ran through to the end
    assert plan.status == PlanStatus.shipped

    events = session.exec(select(PlanEvent).where(PlanEvent.plan_id == plan.id)).all()
    shipped_events = [e for e in events if e.event_type.value == "shipped"]
    # 1 "submitted" event + 7 plane_side tracker steps
    assert len(shipped_events) == 8


def test_screening_captures_dg_exemption_details_for_the_dg_hero_part(session, hero_part):
    plan = _approved_hero_plan(session, hero_part)
    submit_shipment(session, plan, now=NOW)

    events = session.exec(select(PlanEvent).where(PlanEvent.plan_id == plan.id)).all()
    screened = next(e for e in events if e.detail and "screened" in e.detail)
    assert "DG exemption" in screened.detail


def test_to_cargo_chain_runs_four_steps(session, hero_part):
    plan_record = _approved_hero_plan(session, hero_part)
    # override to a to_cargo-routed option so the shorter tracker applies
    plan = choose_alternative(
        session, plan_record, hero_part,
        option=PlanOption.transfer, source="DFW", flight_number=None,
        reason=OverrideReason.spare_needed_elsewhere, note=None, now=NOW,
    )
    assert plan.handoff_route.value == "to_cargo"

    draft = submit_shipment(session, plan, now=NOW)

    assert draft.status.value == "submitted"
    assert plan.shipment_status.value == "delivered"

    events = session.exec(select(PlanEvent).where(PlanEvent.plan_id == plan.id)).all()
    shipped_events = [e for e in events if e.event_type.value == "shipped"]
    # 1 "submitted" event + 4 to_cargo tracker steps
    assert len(shipped_events) == 5


def test_cannot_submit_a_plan_with_no_draft(session, hero_part):
    plan = _proposed_hero_plan(session, hero_part)  # never approved -- no draft was ever built

    with pytest.raises(NoDraftToSubmit):
        submit_shipment(session, plan, now=NOW)


def test_cannot_submit_a_draft_that_is_still_missing_fields(session, hero_part):
    plan = choose_alternative(
        session,
        _proposed_hero_plan(session, hero_part),
        hero_part,
        option=PlanOption.buy,
        source="AeroSource",
        flight_number=None,
        reason=OverrideReason.preferred_vendor,
        note=None,
        now=NOW,
    )
    # a buy plan has no station PALs -- draft stays "draft", not "ready"

    with pytest.raises(DraftNotReady, match="missing"):
        submit_shipment(session, plan, now=NOW)
