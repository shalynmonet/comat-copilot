"""Re-runs every active plan riding on a flight after its schedule or status
changes. The spec's event log calls this "re-routed": a plan recalculated
because of an external trigger, whether or not the winning option actually
changes.
"""

from datetime import datetime, time
from typing import Optional

from sqlmodel import Session, select

from app.ai.explain import explain_plan
from app.models import Aircraft, Flight, InstalledPart, Part, Plan, PlanEvent, PlanEventType, PlanStatus
from app.planner.candidates import build_candidates
from app.planner.score import rank_candidates

RISK_AT_RISK_THRESHOLD = 0.3

ACTIVE_STATUSES = [PlanStatus.proposed, PlanStatus.approved, PlanStatus.at_risk]


def _deadline_for(installed: InstalledPart) -> datetime:
    return datetime.combine(installed.expires_on, time.min)


def replan_for_flight(session: Session, flight: Flight, now: Optional[datetime] = None) -> list[Plan]:
    affected = session.exec(
        select(Plan).where(Plan.flight_number == flight.flight_number, Plan.status.in_(ACTIVE_STATUSES))
    ).all()

    touched = []
    for plan in affected:
        installed = session.get(InstalledPart, plan.installed_serial)
        deadline = _deadline_for(installed)
        candidates = build_candidates(session, installed, now=now)
        ranked = rank_candidates(candidates, deadline)
        best = ranked[0] if ranked else None

        old_route = (plan.option, plan.source, plan.flight_number)

        if best is None:
            plan.risk_score = 1.0
            plan.status = PlanStatus.at_risk
            plan.reason = f"{flight.flight_number} changed; no feasible option remains before the deadline"
        else:
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

        session.add(plan)
        session.add(
            PlanEvent(
                plan_id=plan.id,
                event_type=PlanEventType.re_routed,
                created_at=datetime.now(),
                detail=f"{flight.flight_number} -> {flight.status.value}: {plan.reason}",
            )
        )
        touched.append(plan)

    session.commit()
    for plan in touched:
        session.refresh(plan)
    return touched
