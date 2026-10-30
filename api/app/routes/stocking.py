from typing import Optional

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.db import get_session
from app.models import StockingSuggestion, StockingSuggestionStatus
from app.planner.stocking import StockingSuggestionAlreadyResolved, approve_stocking_suggestion, scan_stocking_suggestions

router = APIRouter(prefix="/stocking", tags=["stocking"])


@router.get("", response_model=list[StockingSuggestion])
def list_stocking_suggestions(status: Optional[StockingSuggestionStatus] = None):
    with get_session() as session:
        scan_stocking_suggestions(session)

        query = select(StockingSuggestion).order_by(StockingSuggestion.created_at)
        if status is not None:
            query = query.where(StockingSuggestion.status == status)
        return session.exec(query).all()


@router.post("/{suggestion_id}/approve", response_model=StockingSuggestion)
def approve_suggestion(suggestion_id: int):
    with get_session() as session:
        suggestion = session.get(StockingSuggestion, suggestion_id)
        if not suggestion:
            raise HTTPException(404, f"stocking suggestion {suggestion_id} not found")
        try:
            return approve_stocking_suggestion(session, suggestion)
        except StockingSuggestionAlreadyResolved as e:
            raise HTTPException(409, str(e))
