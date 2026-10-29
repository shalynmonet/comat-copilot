from typing import Optional

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.adapters.safe_adapter import load_field_specs
from app.db import get_session
from app.models import Plan, ShipmentDraft
from app.planner.shipment_chain import DraftNotReady, NoDraftToSubmit, submit_shipment
from app.schemas import FieldSpecOut

router = APIRouter(prefix="/shipments", tags=["shipments"])


@router.get("/field-specs", response_model=list[FieldSpecOut])
def get_field_specs():
    return [FieldSpecOut(name=s.name, label=s.label, required=s.required) for s in load_field_specs()]


@router.get("", response_model=list[ShipmentDraft])
def list_shipments(plan_id: Optional[int] = None):
    with get_session() as session:
        query = select(ShipmentDraft).order_by(ShipmentDraft.id)
        if plan_id is not None:
            query = query.where(ShipmentDraft.plan_id == plan_id)
        return session.exec(query).all()


@router.get("/{draft_id}", response_model=ShipmentDraft)
def get_shipment(draft_id: int):
    with get_session() as session:
        draft = session.get(ShipmentDraft, draft_id)
        if not draft:
            raise HTTPException(404, f"shipment draft {draft_id} not found")
        return draft


@router.post("/{draft_id}/submitted")
def mark_submitted(draft_id: int):
    with get_session() as session:
        draft = session.get(ShipmentDraft, draft_id)
        if not draft:
            raise HTTPException(404, f"shipment draft {draft_id} not found")
        plan = session.get(Plan, draft.plan_id)
        if not plan:
            raise HTTPException(404, f"plan {draft.plan_id} not found")

        try:
            submitted = submit_shipment(session, plan)
        except NoDraftToSubmit as e:
            raise HTTPException(409, str(e))
        except DraftNotReady as e:
            raise HTTPException(409, str(e))

        session.refresh(plan)
        return {"plan": plan, "draft": submitted}
