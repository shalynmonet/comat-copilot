"""Re-runs every active plan riding on a flight after its schedule or status
changes. The spec's event log calls this "re-routed": a plan recalculated
because of an external trigger, whether or not the winning option actually
changes.

A plan a human has already *approved* is handled more carefully: its
committed option is never silently rewritten. The flight change instead
flags it at_risk, supersedes any shipment draft already built for it (it
was built for the now-stale committed option), and stages the system's
new recommendation -- priority included -- in the pending_* fields, where
POST /plans/{id}/approve will pick it up. A plan that was never approved
(still proposed, or already flagged at_risk with nothing committed yet)
keeps the old auto-update behavior, since there's no prior human sign-off
or submitted paperwork to protect.
"""

from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from app.ai.explain import explain_plan
from app.models import (
    Aircraft,
    Flight,
    InstalledPart,
    Part,
    Plan,
    PlanEvent,
    PlanEventType,
    PlanStatus,
    ShipmentDraft,
    ShipmentDraftStatus,
)
from app.planner.candidates import build_candidates, deadline_for
from app.planner.decisions import clear_pending
from app.planner.priority_rules import PRIORITY_RANK, PRIORITY_LABELS, build_reason_line, compute_priority_assignment, priority_reason_fragment
from app.planner.score import rank_candidates

RISK_AT_RISK_THRESHOLD = 0.3

ACTIVE_STATUSES = [PlanStatus.proposed, PlanStatus.approved, PlanStatus.at_risk]


def _supersede_existing_drafts(session: Session, plan_id: int, now: datetime) -> None:
    """Any shipment draft already built for this plan was built for the
    option that's now stale (or no longer committed) -- mark it
    superseded rather than leaving it looking current."""
    drafts = session.exec(
        select(ShipmentDraft).where(
            ShipmentDraft.plan_id == plan_id, ShipmentDraft.status != ShipmentDraftStatus.superseded
        )
    ).all()
    for draft in drafts:
        draft.status = ShipmentDraftStatus.superseded
        draft.updated_at = now
        session.add(draft)


def _pending_reason_for(
    session: Session,
    installed: InstalledPart,
    part: Part,
    aircraft: Aircraft,
    best,
    rejected,
    old_priority,
    is_ron_package: bool,
    now: datetime,
) -> str:
    """The reason shown for a *pending* recommendation, before anyone has
    approved it -- including a priority note, and an explicit callout
    when this delay pushed the priority up (e.g. STD -> MRD, the spec's
    "upgrade to MRD and say so in the reason line")."""
    assignment = compute_priority_assignment(
        session, installed, part, best.candidate.option, best.candidate.source,
        best.candidate.flight_number, is_ron_package, now,
    )
    why = priority_reason_fragment(assignment.priority, assignment.viable_flight_count, assignment.part_expired)
    priority_line = build_reason_line(assignment.priority, assignment.handoff_route, why)

    base_reason = explain_plan(
        best, rejected, part.description, installed.tail_number, aircraft.overnight_station, installed.expires_on
    )

    old_rank = PRIORITY_RANK.get(old_priority, 0) if old_priority else 0
    new_rank = PRIORITY_RANK.get(assignment.priority, 0)
    if old_priority is not None and new_rank > old_rank:
        return f"Upgraded to {PRIORITY_LABELS[assignment.priority]} -- {why}. {base_reason}"
    return f"{priority_line} {base_reason}"


def replan_for_flight(session: Session, flight: Flight, now: Optional[datetime] = None) -> list[Plan]:
    effective_now = now or datetime.now()
    affected = session.exec(
        select(Plan).where(Plan.flight_number == flight.flight_number, Plan.status.in_(ACTIVE_STATUSES))
    ).all()

    touched = []
    for plan in affected:
        installed = session.get(InstalledPart, plan.installed_serial)
        deadline = deadline_for(installed)
        candidates = build_candidates(session, installed, now=now)
        ranked = rank_candidates(candidates, deadline)
        best = ranked[0] if ranked else None
        was_approved = plan.status == PlanStatus.approved

        if was_approved:
            _supersede_existing_drafts(session, plan.id, effective_now)
            plan.status = PlanStatus.at_risk
            if best is None:
                clear_pending(plan)
                event_detail = (
                    f"{flight.flight_number} -> {flight.status.value}: the committed plan is at risk "
                    "and no feasible alternative remains before the deadline"
                )
            else:
                rejected = [r.candidate for r in ranked[1:]]
                part = session.get(Part, installed.part_number)
                aircraft = session.get(Aircraft, installed.tail_number)
                plan.pending_option = best.candidate.option
                plan.pending_source = best.candidate.source
                plan.pending_flight_number = best.candidate.flight_number
                plan.pending_cost = best.candidate.cost
                plan.pending_risk_score = best.risk_score
                plan.pending_reason = _pending_reason_for(
                    session, installed, part, aircraft, best, rejected, plan.priority, plan.is_ron_package, effective_now
                )
                event_detail = (
                    f"{flight.flight_number} -> {flight.status.value}: committed plan at risk; new "
                    f"recommendation ({best.candidate.option.value} from {best.candidate.source}) awaiting "
                    f"approval -- {plan.pending_reason}"
                )
        elif best is None:
            plan.risk_score = 1.0
            plan.status = PlanStatus.at_risk
            plan.reason = f"{flight.flight_number} changed; no feasible option remains before the deadline"
            event_detail = f"{flight.flight_number} -> {flight.status.value}: {plan.reason}"
        else:
            old_route = (plan.option, plan.source, plan.flight_number)
            rejected = [r.candidate for r in ranked[1:]]
            part = session.get(Part, installed.part_number)
            aircraft = session.get(Aircraft, installed.tail_number)

            new_route = (best.candidate.option, best.candidate.source, best.candidate.flight_number)
            plan.option = best.candidate.option
            plan.source = best.candidate.source
            plan.flight_number = best.candidate.flight_number
            plan.cost = best.candidate.cost
            plan.risk_score = best.risk_score
            plan.reason = explain_plan(
                best, rejected, part.description, installed.tail_number, aircraft.overnight_station, installed.expires_on
            )
            if new_route != old_route:
                plan.status = PlanStatus.re_routed
            elif best.risk_score >= RISK_AT_RISK_THRESHOLD:
                plan.status = PlanStatus.at_risk
            # else: same route, still comfortably on time -- leave status as-is
            event_detail = f"{flight.flight_number} -> {flight.status.value}: {plan.reason}"

        session.add(plan)
        session.add(
            PlanEvent(
                plan_id=plan.id,
                event_type=PlanEventType.re_routed,
                created_at=effective_now,
                detail=event_detail,
            )
        )
        touched.append(plan)

    session.commit()
    for plan in touched:
        session.refresh(plan)
    return touched
