"""Human decisions on a plan: approving the current (or a flight-change's
staged pending) recommendation, or overriding it with a different feasible
option and saying why. Kept separate from routes/plans.py, and from
replan.py's automated recalculation, so each is unit-testable on its own.
"""

from datetime import datetime
from typing import Optional

from sqlmodel import Session

from app.models import (
    OVERRIDE_REASON_LABELS,
    InstalledPart,
    OverrideReason,
    Plan,
    PlanEvent,
    PlanEventType,
    PlanOption,
)
from app.planner.candidates import build_candidates, deadline_for
from app.planner.score import score_candidate
from app.planner.verification import finish_approval


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
    plan.pending_spare_serial = None


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
        plan.spare_serial = plan.pending_spare_serial
        clear_pending(plan)

    # finish_approval() computes priority/profile/route and either builds
    # a ready draft or -- if the committed spare is below the confidence
    # threshold -- creates a verify_task and parks the plan instead (see
    # app/planner/verification.py).
    return finish_approval(session, plan, now)


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
    plan.spare_serial = match.spare_serial
    plan.reason = f"Planner override: {reason_text}"
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
    return finish_approval(session, plan, now)
