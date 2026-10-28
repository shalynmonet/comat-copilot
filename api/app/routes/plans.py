from datetime import datetime, time
from typing import Optional

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.ai.explain import explain_plan
from app.db import get_session
from app.models import Aircraft, InstalledPart, Part, Plan, PlanEvent, PlanEventType, PlanStatus
from app.planner.candidates import build_candidates
from app.planner.score import rank_candidates, to_plan
from app.schemas import CandidateOut, PlanCreateRequest

router = APIRouter(prefix="/plans", tags=["plans"])


def _deadline_for(installed: InstalledPart) -> datetime:
    return datetime.combine(installed.expires_on, time.min)


def _get_installed_or_404(session, serial: str) -> InstalledPart:
    installed = session.get(InstalledPart, serial)
    if not installed:
        raise HTTPException(404, f"installed part {serial} not found")
    return installed


@router.get("/candidates/{installed_serial}", response_model=list[CandidateOut])
def get_candidates(installed_serial: str):
    with get_session() as session:
        installed = _get_installed_or_404(session, installed_serial)
        candidates = build_candidates(session, installed)
        ranked = rank_candidates(candidates, deadline=_deadline_for(installed))
        return [
            CandidateOut(
                option=r.candidate.option,
                source=r.candidate.source,
                flight_number=r.candidate.flight_number,
                cost=r.candidate.cost,
                eta=r.candidate.eta,
                risk_score=r.risk_score,
                score=r.score,
                detail=r.candidate.detail,
            )
            for r in ranked
        ]


@router.post("", response_model=Plan)
def create_plan(body: PlanCreateRequest):
    with get_session() as session:
        installed = _get_installed_or_404(session, body.installed_serial)
        candidates = build_candidates(session, installed)
        ranked = rank_candidates(candidates, deadline=_deadline_for(installed))
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
        plan = session.get(Plan, plan_id)
        if not plan:
            raise HTTPException(404, f"plan {plan_id} not found")
        return plan


@router.post("/{plan_id}/approve", response_model=Plan)
def approve_plan(plan_id: int):
    with get_session() as session:
        plan = session.get(Plan, plan_id)
        if not plan:
            raise HTTPException(404, f"plan {plan_id} not found")

        plan.status = PlanStatus.approved
        session.add(plan)
        session.add(
            PlanEvent(plan_id=plan.id, event_type=PlanEventType.approved, created_at=datetime.now())
        )
        session.commit()
        session.refresh(plan)
        return plan
