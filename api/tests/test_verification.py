"""Covers verification.py: a low-confidence committed spare creates a
verify_task and parks the plan in pending_verification instead of
building a ready draft; a photo match clears it and lets the plan
continue; a photo mismatch flags the spare phantom, dings the station's
discrepancy_rate, and re-plans to the next feasible source.
"""

import pytest
from sqlmodel import select

from app.adapters import verify_tag
from app.models import (
    InventoryItem,
    PlanEvent,
    PlanEventType,
    PlanOption,
    PlanStatus,
    ShipmentDraft,
    Station,
    VerifyTask,
    VerifyTaskStatus,
)
from app.planner.candidates import build_candidates
from app.planner.decisions import approve_plan
from app.planner.score import pick_best, to_plan
from app.planner.verification import VerifyTaskAlreadyResolved, needs_verification, resolve_verify_task
from tests.conftest import DEADLINE, NOW


def _make_low_confidence(session, serial: str, station_code: str) -> None:
    """Degrades the DFW spare/station enough to trip the verification gate."""
    item = session.get(InventoryItem, serial)
    item.move_count_30d = 5
    session.add(item)
    station = session.get(Station, station_code)
    station.discrepancy_rate = 0.4
    session.add(station)
    session.commit()


def _proposed_hero_plan(session, hero_part):
    candidates = build_candidates(session, hero_part, now=NOW)
    best = pick_best(candidates, deadline=DEADLINE)
    plan = to_plan(hero_part.serial, best, status=PlanStatus.proposed)
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


def test_needs_verification_is_none_for_a_trustworthy_spare(session, hero_part):
    plan = _proposed_hero_plan(session, hero_part)
    assert needs_verification(session, plan, NOW) is None


def test_approving_against_a_low_confidence_spare_creates_a_verify_task(session, hero_part):
    _make_low_confidence(session, "INV-DFW-OXY-BTL-02-1", "DFW")
    plan = _proposed_hero_plan(session, hero_part)

    result = approve_plan(session, plan, now=NOW)

    assert result.status == PlanStatus.pending_verification
    task = session.exec(select(VerifyTask).where(VerifyTask.plan_id == plan.id)).one()
    assert task.status == VerifyTaskStatus.open
    assert task.inventory_serial == "INV-DFW-OXY-BTL-02-1"
    assert task.confidence_at_creation < 0.6

    events = session.exec(select(PlanEvent).where(PlanEvent.plan_id == plan.id)).all()
    assert any(e.event_type == PlanEventType.verification_required for e in events)
    # no draft built yet -- the plan is parked, not ready
    assert session.exec(select(ShipmentDraft).where(ShipmentDraft.plan_id == plan.id)).first() is None


def test_match_resolves_the_task_and_lets_the_plan_continue(session, hero_part):
    _make_low_confidence(session, "INV-DFW-OXY-BTL-02-1", "DFW")
    plan = approve_plan(session, _proposed_hero_plan(session, hero_part), now=NOW)
    assert plan.status == PlanStatus.pending_verification
    task = session.exec(select(VerifyTask).where(VerifyTask.plan_id == plan.id)).one()

    item = session.get(InventoryItem, task.inventory_serial)
    # A photo whose extracted fields exactly match this record -- a
    # dedicated fake filename rather than the seeded demo images, which
    # target a different serial.
    verify_tag._MOCK_READS["unit-test-match.jpg"] = verify_tag.ExtractedTag(
        part_number=item.part_number,
        serial=item.serial,
        condition=item.condition.value,
        read_confidence=0.99,
        raw_text="unit test",
    )

    resolved = resolve_verify_task(session, task, "unit-test-match.jpg", NOW, verified_by="Jane (Stores)")

    assert resolved.status == VerifyTaskStatus.matched
    session.refresh(item)
    assert item.last_verified_at == NOW
    assert item.verified_by == "Jane (Stores)"
    assert item.phantom_flag is False
    assert item.confidence >= 0.6

    session.refresh(plan)
    assert plan.status == PlanStatus.approved
    draft = session.exec(select(ShipmentDraft).where(ShipmentDraft.plan_id == plan.id)).one()
    assert draft.status.value == "ready"


def test_mismatch_flags_phantom_bumps_discrepancy_and_replans(session, hero_part):
    _make_low_confidence(session, "INV-DFW-OXY-BTL-02-1", "DFW")
    plan = approve_plan(session, _proposed_hero_plan(session, hero_part), now=NOW)
    task = session.exec(select(VerifyTask).where(VerifyTask.plan_id == plan.id)).one()

    station_before = session.get(Station, "DFW")
    discrepancy_before = station_before.discrepancy_rate

    resolved = resolve_verify_task(session, task, "tag-ord-oxy-btl-02-mismatch.jpg", NOW)

    assert resolved.status == VerifyTaskStatus.mismatched
    item = session.get(InventoryItem, task.inventory_serial)
    assert item.phantom_flag is True

    session.refresh(station_before)
    assert station_before.discrepancy_rate > discrepancy_before

    session.refresh(plan)
    # the only DFW spare is now phantom-flagged and excluded -- the
    # planner falls back to the fixture's legitimate AeroSource buy
    # option, which doesn't depend on any spare's confidence at all.
    assert plan.option == PlanOption.buy
    assert plan.status == PlanStatus.approved

    events = session.exec(select(PlanEvent).where(PlanEvent.plan_id == plan.id)).all()
    assert any(e.event_type == PlanEventType.phantom_flagged for e in events)
    assert any(e.event_type == PlanEventType.re_routed for e in events)


def test_resolving_an_already_resolved_task_raises(session, hero_part):
    _make_low_confidence(session, "INV-DFW-OXY-BTL-02-1", "DFW")
    plan = approve_plan(session, _proposed_hero_plan(session, hero_part), now=NOW)
    task = session.exec(select(VerifyTask).where(VerifyTask.plan_id == plan.id)).one()
    resolve_verify_task(session, task, "tag-ord-oxy-btl-02-mismatch.jpg", NOW)

    with pytest.raises(VerifyTaskAlreadyResolved):
        resolve_verify_task(session, task, "tag-ord-oxy-btl-02-mismatch.jpg", NOW)
