from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.ai.explain import explain_plan
from app.db import get_session
from app.models import Aircraft, InstalledPart, Part, Plan, PlanEvent, PlanEventType, PlanStatus
from app.planner.candidates import build_candidates, deadline_for
from app.planner.decisions import NoSuchCandidate, approve_plan, choose_alternative
from app.planner.score import rank_candidates, to_plan
from app.schemas import CandidateOut, ChoosePlanRequest, PlanCreateRequest

router = APIRouter(prefix="/plans", tags=["plans"])


def _get_installed_or_404(session, serial: str) -> InstalledPart:
    installed = session.get(InstalledPart, serial)
    if not installed:
        raise HTTPException(404, f"installed part {serial} not found")
    return installed


def _get_plan_or_404(session, plan_id: int) -> Plan:
    plan = session.get(Plan, plan_id)
    if not plan:
        raise HTTPException(404, f"plan {plan_id} not found")
    return plan


@router.get("/candidates/{installed_serial}", response_model=list[CandidateOut])
def get_candidates(installed_serial: str):
    with get_session() as session:
        installed = _get_installed_or_404(session, installed_serial)
        all_candidates = build_candidates(session, installed, include_disqualified=True)
        feasible = [c for c in all_candidates if not c.disqualified]
        disqualified = [c for c in all_candidates if c.disqualified]
        ranked = rank_candidates(feasible, deadline=deadline_for(installed))

        out = [
            CandidateOut(
                option=r.candidate.option,
                source=r.candidate.source,
                flight_number=r.candidate.flight_number,
                cost=r.candidate.cost,
                eta=r.candidate.eta,
                risk_score=r.risk_score,
                score=r.score,
                detail=r.candidate.detail,
                disqualified=False,
                disqualified_reason=None,
            )
            for r in ranked
        ]
        out += [
            CandidateOut(
                option=c.option,
                source=c.source,
                flight_number=c.flight_number,
                cost=c.cost,
                eta=c.eta,
                risk_score=None,
                score=None,
                detail=c.detail,
                disqualified=True,
                disqualified_reason=c.disqualified_reason,
            )
            for c in disqualified
        ]
        return out


@router.post("", response_model=Plan)
def create_plan(body: PlanCreateRequest):
    with get_session() as session:
        installed = _get_installed_or_404(session, body.installed_serial)
        candidates = build_candidates(session, installed)
        ranked = rank_candidates(candidates, deadline=deadline_for(installed))
        if not ranked:
            raise HTTPException(409, "no feasible option found before the deadline")
        best, rejected = ranked[0], [r.candidate for r in ranked[1:]]

        part = session.get(Part, installed.part_number)
        aircraft = session.get(Aircraft, installed.tail_number)

        plan = to_plan(installed.serial, best)
        plan.reason = explain_plan(
            best, rejected, part.description, installed.tail_number, aircraft.overnight_station, installed.expires_on
        )
        session.add(plan)
        session.commit()
        session.refresh(plan)

        session.add(
            PlanEvent(
                plan_id=plan.id,
                event_type=PlanEventType.created,
                created_at=datetime.now(),
                detail=plan.reason,
            )
        )
        session.commit()
        session.refresh(plan)
        return plan


@router.get("", response_model=list[Plan])
def list_plans(status: Optional[PlanStatus] = None):
    with get_session() as session:
        query = select(Plan)
        if status is not None:
            query = query.where(Plan.status == status)
        return session.exec(query).all()


@router.get("/{plan_id}", response_model=Plan)
def get_plan(plan_id: int):
    with get_session() as session:
        return _get_plan_or_404(session, plan_id)


@router.post("/{plan_id}/approve", response_model=Plan)
def approve(plan_id: int):
    with get_session() as session:
        plan = _get_plan_or_404(session, plan_id)
        return approve_plan(session, plan)


@router.post("/{plan_id}/choose", response_model=Plan)
def choose(plan_id: int, body: ChoosePlanRequest):
    """A human picks a feasible option other than the system's recommendation."""
    with get_session() as session:
        plan = _get_plan_or_404(session, plan_id)
        installed = _get_installed_or_404(session, plan.installed_serial)
        try:
            return choose_alternative(
                session,
                plan,
                installed,
                body.option,
                body.source,
                body.flight_number,
                body.reason,
                body.note,
            )
        except NoSuchCandidate:
            raise HTTPException(409, "that option is no longer available")
