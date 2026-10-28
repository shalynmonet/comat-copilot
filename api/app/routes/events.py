from typing import Optional

from fastapi import APIRouter
from sqlmodel import select

from app.db import get_session
from app.models import PlanEvent

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[PlanEvent])
def list_events(plan_id: Optional[int] = None):
    with get_session() as session:
        query = select(PlanEvent).order_by(PlanEvent.created_at)
        if plan_id is not None:
            query = query.where(PlanEvent.plan_id == plan_id)
        return session.exec(query).all()
