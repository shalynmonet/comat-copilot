"""Re-runs every active plan riding on a flight after its schedule or status
changes. The spec's event log calls this "re-routed": a plan recalculated
because of an external trigger, whether or not the winning option actually
changes.

A plan a human has already *approved* is handled more carefully: its
committed option is never silently rewritten. The flight change instead
flags it at_risk and stages the system's new recommendation in the
pending_* fields, where POST /plans/{id}/approve will pick it up. A plan
that was never approved (still proposed, or already flagged at_risk with
nothing committed yet) keeps the old auto-update behavior, since there's no
prior human sign-off to protect.
"""

from datetime import datetime, time
from typing import Optional

from sqlmodel import Session, select

from app.ai.explain import explain_plan
from app.models import Aircraft, Flight, InstalledPart, Part, Plan, PlanEvent, PlanEventType, PlanStatus
from app.planner.candidates import build_candidates, deadline_for
from app.planner.decisions import clear_pending
from app.planner.score import rank_candidates

RISK_AT_RISK_THRESHOLD = 0.3

ACTIVE_STATUSES = [PlanStatus.proposed, PlanStatus.approved, PlanStatus.at_risk]


def replan_for_flight(session: Session, flight: Flight, now: Optional[datetime] = None) -> list[Plan]:
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
                plan.pending_reason = explain_plan(
                    best,
                    rejected,
                    part.description,
                    installed.tail_number,
                    aircraft.overnight_station,
                    installed.expires_on,
                )
                event_detail = (
                    f"{flight.flight_number} -> {flight.status.value}: committed plan at risk; new "
                    f"recommendation ({best.candidate.option.value} from {best.candidate.source}) awaiting approval"
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
                created_at=datetime.now(),
                detail=event_detail,
            )
        )
        touched.append(plan)

    session.commit()
    for plan in touched:
        session.refresh(plan)
    return touched
