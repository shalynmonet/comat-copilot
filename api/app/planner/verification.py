"""Inventory-confidence gate on human decisions, and what happens when a
verify_task resolves.

Approving or overriding a plan doesn't go straight to a ready draft
anymore if the plan's committed spare is below the confidence threshold
(see app/planner/confidence.py) -- finish_approval() is the shared tail
decisions.py calls instead: it builds the draft when the spare is
trustworthy enough, or creates a verify_task and parks the plan in
pending_verification when it isn't.

resolve_verify_task() is what a Stores photo upload drives (see
app/adapters/verify_tag.py for the mocked read): a match clears the
spare and lets the plan continue past finish_approval(); a mismatch
flags the spare phantom, dings the station's discrepancy_rate, and
re-plans to the next feasible source -- which may itself need
verification, so this can chain.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Session

from app.adapters.safe_adapter import build_draft
from app.adapters.verify_tag import ExtractedTag, get_tag_verify_adapter
from app.config import load_settings
from app.models import (
    InstalledPart,
    InventoryItem,
    Plan,
    PlanEvent,
    PlanEventType,
    PlanStatus,
    PlanOption,
    ShipmentDraft,
    ShipmentDraftStatus,
    Station,
    VerifyTask,
    VerifyTaskStatus,
)
from app.planner.candidates import build_candidates, deadline_for
from app.planner.confidence import ConfidenceResult, bump_station_discrepancy_rate, confidence_for_item, refresh_confidence
from app.planner.priority_rules import assign_priority_profile_route
from app.planner.score import pick_best


class VerifyTaskAlreadyResolved(Exception):
    """The task was already matched or mismatched -- photos only resolve a task once."""


def needs_verification(
    session: Session, plan: Plan, now: datetime
) -> Optional[tuple[InventoryItem, ConfidenceResult]]:
    """None if this plan's committed option doesn't depend on a spare
    (buy), or the spare it depends on is trustworthy enough. Otherwise
    the spare and why it's below the verification threshold."""
    if plan.option not in (PlanOption.comat, PlanOption.transfer) or not plan.spare_serial:
        return None
    item = session.get(InventoryItem, plan.spare_serial)
    if not item:
        return None
    result = confidence_for_item(session, item, now)
    if result.confidence < load_settings().confidence.verification_threshold:
        return item, result
    return None


def _create_verify_task(session: Session, plan: Plan, item: InventoryItem, result: ConfidenceResult, now: datetime) -> VerifyTask:
    task = VerifyTask(
        inventory_serial=item.serial,
        plan_id=plan.id,
        reason=result.top_reason,
        confidence_at_creation=result.confidence,
        created_at=now,
    )
    session.add(task)
    return task


def _build_and_save_draft(session: Session, plan: Plan, now: datetime) -> None:
    result = build_draft(session, plan)
    draft = ShipmentDraft(
        plan_id=plan.id,
        fields=result.fields,
        status=ShipmentDraftStatus(result.status),
        missing_fields=result.missing_fields,
        created_at=now,
        updated_at=now,
    )
    session.add(draft)

    if result.missing_fields:
        detail = f"draft created, status=draft -- missing: {', '.join(result.missing_fields)}"
    else:
        detail = "draft created, status=ready for Stores to review and submit"
    session.add(PlanEvent(plan_id=plan.id, event_type=PlanEventType.draft_created, created_at=now, detail=detail))


def finish_approval(session: Session, plan: Plan, now: datetime) -> Plan:
    """Shared tail of approve_plan/choose_alternative (and of a verify_task
    resolving): computes priority/profile/route, then either builds a
    ready draft or -- if the committed spare is below the confidence
    threshold -- creates a verify_task and parks the plan instead."""
    assign_priority_profile_route(session, plan, now)

    verification = needs_verification(session, plan, now)
    if verification:
        item, result = verification
        plan.status = PlanStatus.pending_verification
        session.add(plan)
        session.add(
            PlanEvent(
                plan_id=plan.id,
                event_type=PlanEventType.verification_required,
                created_at=now,
                detail=(
                    f"spare {item.serial} at {item.station} needs photo verification before this "
                    f"plan can proceed -- {result.top_reason} (confidence {result.confidence:.2f})"
                ),
            )
        )
        _create_verify_task(session, plan, item, result, now)
    else:
        plan.status = PlanStatus.approved
        session.add(plan)
        session.add(PlanEvent(plan_id=plan.id, event_type=PlanEventType.approved, created_at=now))
        _build_and_save_draft(session, plan, now)

    session.commit()
    session.refresh(plan)
    return plan


def _describe_mismatch(item: InventoryItem, extracted: ExtractedTag) -> str:
    if extracted.part_number is None and extracted.serial is None:
        return "the tag couldn't be read"
    diffs = []
    if extracted.part_number != item.part_number:
        diffs.append(f"part {extracted.part_number or 'unreadable'} (expected {item.part_number})")
    if extracted.serial != item.serial:
        diffs.append(f"serial {extracted.serial or 'unreadable'} (expected {item.serial})")
    if extracted.condition != item.condition.value:
        diffs.append(f"condition {extracted.condition or 'unreadable'} (expected {item.condition.value})")
    return "tag shows " + ", ".join(diffs)


def _replan_to_next_source(session: Session, plan: Plan, now: datetime) -> Plan:
    """A phantom-flagged spare is now excluded from candidates (see
    candidates.py) -- rebuild and commit to the next best feasible
    option, which may itself trip the verification gate."""
    installed = session.get(InstalledPart, plan.installed_serial)
    deadline = deadline_for(installed)
    candidates = build_candidates(session, installed, now=now)
    best = pick_best(candidates, deadline)

    if best is None:
        plan.status = PlanStatus.at_risk
        plan.reason = "the committed spare turned out to be phantom and no feasible alternative remains"
        session.add(plan)
        session.add(
            PlanEvent(plan_id=plan.id, event_type=PlanEventType.re_routed, created_at=now, detail=plan.reason)
        )
        session.commit()
        session.refresh(plan)
        return plan

    plan.option = best.candidate.option
    plan.source = best.candidate.source
    plan.flight_number = best.candidate.flight_number
    plan.cost = best.candidate.cost
    plan.risk_score = best.risk_score
    plan.spare_serial = best.candidate.spare_serial
    plan.reason = f"re-planned after a phantom-part discrepancy -- {best.candidate.detail}"
    session.add(plan)
    session.add(
        PlanEvent(
            plan_id=plan.id,
            event_type=PlanEventType.re_routed,
            created_at=now,
            detail=(
                f"re-planned to {best.candidate.option.value} from {best.candidate.source} "
                "after a phantom-part discrepancy"
            ),
        )
    )
    session.commit()
    session.refresh(plan)
    return finish_approval(session, plan, now)


def resolve_verify_task(
    session: Session, task: VerifyTask, photo_filename: str, now: datetime, verified_by: str = "Stores"
) -> VerifyTask:
    if task.status != VerifyTaskStatus.open:
        raise VerifyTaskAlreadyResolved(f"verify_task {task.id} is already {task.status.value}")

    item = session.get(InventoryItem, task.inventory_serial)
    plan = session.get(Plan, task.plan_id)

    extracted = get_tag_verify_adapter().read_tag(photo_filename)
    task.photo_filename = photo_filename
    task.extracted_part_number = extracted.part_number
    task.extracted_serial = extracted.serial
    task.extracted_condition = extracted.condition
    task.resolved_at = now

    is_match = (
        extracted.part_number == item.part_number
        and extracted.serial == item.serial
        and extracted.condition == item.condition.value
    )

    if is_match:
        task.status = VerifyTaskStatus.matched
        item.last_verified_at = now
        item.verified_by = verified_by
        item.phantom_flag = False
        result = refresh_confidence(session, item, now)
        session.add(
            PlanEvent(
                plan_id=plan.id,
                event_type=PlanEventType.verified,
                created_at=now,
                detail=(
                    f"Stores verified {item.serial} at {item.station} by photo -- tag matches record "
                    f"(part {extracted.part_number}, serial {extracted.serial}). Confidence now {result.confidence:.2f}."
                ),
            )
        )
        session.add(task)
        session.commit()
        finish_approval(session, plan, now)  # re-checks confidence -- now clears the gate
    else:
        task.status = VerifyTaskStatus.mismatched
        item.phantom_flag = True
        station = session.get(Station, item.station)
        if station:
            bump_station_discrepancy_rate(session, station)
        refresh_confidence(session, item, now)

        session.add(
            PlanEvent(
                plan_id=plan.id,
                event_type=PlanEventType.phantom_flagged,
                created_at=now,
                detail=f"Stores photo-verified {item.serial} at {item.station} -- {_describe_mismatch(item, extracted)}.",
            )
        )
        session.add(task)
        session.commit()
        _replan_to_next_source(session, plan, now)

    session.refresh(task)
    return task
