from typing import Optional

from fastapi import APIRouter
from sqlmodel import select

from app.db import get_session
from app.models import ShippingRequest, ShippingRequestStatus

router = APIRouter(prefix="/requests", tags=["requests"])


@router.get("", response_model=list[ShippingRequest])
def list_requests(status: Optional[ShippingRequestStatus] = None):
    with get_session() as session:
        query = select(ShippingRequest).order_by(ShippingRequest.needed_by)
        if status is not None:
            query = query.where(ShippingRequest.status == status)
        return session.exec(query).all()
