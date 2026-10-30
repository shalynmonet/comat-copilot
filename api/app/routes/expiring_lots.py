from typing import Optional

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.config import load_settings
from app.db import get_session
from app.models import ExpiringLotAction, ExpiringLotActionStatus
from app.planner.expiring_lots import ExpiringLotActionAlreadyResolved, approve_lot_action, scan_expiring_lots

router = APIRouter(prefix="/expiring-lots", tags=["expiring-lots"])


@router.get("", response_model=list[ExpiringLotAction])
def list_expiring_lot_actions(status: Optional[ExpiringLotActionStatus] = None, window_days: Optional[int] = None):
    with get_session() as session:
        window = window_days or load_settings().expiring_lots.window_days
        scan_expiring_lots(session, window)

        query = select(ExpiringLotAction).order_by(ExpiringLotAction.created_at)
        if status is not None:
            query = query.where(ExpiringLotAction.status == status)
        return session.exec(query).all()


@router.post("/{action_id}/approve", response_model=ExpiringLotAction)
def approve_expiring_lot_action(action_id: int):
    with get_session() as session:
        action = session.get(ExpiringLotAction, action_id)
        if not action:
            raise HTTPException(404, f"expiring-lot action {action_id} not found")
        try:
            return approve_lot_action(session, action)
        except ExpiringLotActionAlreadyResolved as e:
            raise HTTPException(409, str(e))
