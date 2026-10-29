"""Human decisions on a plan: approving the current (or a flight-change's
staged pending) recommendation, or overriding it with a different feasible
option and saying why. Kept separate from routes/plans.py, and from
replan.py's automated recalculation, so each is unit-testable on its own.
"""

from datetime import datetime
from typing import Optional

from sqlmodel import Session

from app.adapters.safe_adapter import build_draft
from app.models import (
    OVERRIDE_REASON_LABELS,
    InstalledPart,
    OverrideReason,
    Plan,
    PlanEvent,
    PlanEventType,
    PlanOption,
    PlanStatus,
    ShipmentDraft,
    ShipmentDraftStatus,
)
from app.planner.candidates import build_candidates, deadline_for
from app.planner.priority_rules import assign_priority_profile_route
from app.planner.score import score_candidate


class NoSuchCandidate(Exception):
    """Raised when the chosen (option, source, flight_number) no longer
    matches a feasible candidate -- e.g. it was overtaken by events between
    the browser fetching candidates and the human clicking a button."""


def clear_pending(plan: Plan) -> None:
    plan.pending_option = None
    plan.pending_source = None
    plan.pending_flight_number = None
    plan.pending_cost = None
    plan.pending_risk_score = None
    plan.pending_reason = None


def _build_and_save_draft(session: Session, plan: Plan, now: datetime) -> None:
    """On approval: compute the plan's priority/profile/route, then build
    and save a SAFE-ready draft for Stores to review. Copilot never
    submits it -- that's a human action (see POST /shipments/{id}/submitted
    in a later step). Logged as a "draft created" plan_event.
    """
    assign_priority_profile_route(session, plan, now)
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


def approve_plan(session: Session, plan: Plan, now: Optional[datetime] = None) -> Plan:
    now = now or datetime.now()
    if plan.pending_option is not None:
        # A flight change staged a new recommendation while this plan was
        # approved -- approving now adopts it.
        plan.option = plan.pending_option
        plan.source = plan.pending_source
        plan.flight_number = plan.pending_flight_number
        plan.cost = plan.pending_cost
        plan.risk_score = plan.pending_risk_score
        plan.reason = plan.pending_reason
        clear_pending(plan)

    plan.status = PlanStatus.approved
    session.add(plan)
    session.add(PlanEvent(plan_id=plan.id, event_type=PlanEventType.approved, created_at=now))
    _build_and_save_draft(session, plan, now)
    session.commit()
    session.refresh(plan)
    return plan


def choose_alternative(
    session: Session,
    plan: Plan,
    installed: InstalledPart,
    option: PlanOption,
    source: str,
    flight_number: Optional[str],
    reason: OverrideReason,
    note: Optional[str],
    now: Optional[datetime] = None,
) -> Plan:
    now = now or datetime.now()
    deadline = deadline_for(installed)
    candidates = build_candidates(session, installed)  # feasible only
    match = next(
        (
            c
            for c in candidates
            if c.option == option and c.source == source and c.flight_number == flight_number
        ),
        None,
    )
    if not match:
        raise NoSuchCandidate()

    label = OVERRIDE_REASON_LABELS[reason]
    note_clean = note.strip() if note else None
    reason_text = note_clean if (reason == OverrideReason.other and note_clean) else label

    scored = score_candidate(match, deadline)
    plan.option = match.option
    plan.source = match.source
    plan.flight_number = match.flight_number
    plan.cost = match.cost
    plan.risk_score = scored.risk_score
    plan.reason = f"Planner override: {reason_text}"
    plan.status = PlanStatus.approved
    clear_pending(plan)

    session.add(plan)
    via = f" via {match.flight_number}" if match.flight_number else ""
    session.add(
        PlanEvent(
            plan_id=plan.id,
            event_type=PlanEventType.overridden,
            created_at=now,
            detail=f"chose {match.option.value} from {match.source}{via} instead -- {reason_text}",
        )
    )
    _build_and_save_draft(session, plan, now)
    session.commit()
    session.refresh(plan)
    return plan
