from datetime import datetime
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from sqlmodel import select

from app.adapters.m3_adapter import get_m3_adapter
from app.db import get_session
from app.models import PartRequest, PartRequestStatus
from app.planner.pick_issue import PartRequestAlreadyResolved, resolve_pick
from app.schemas import PartRequestCreate

router = APIRouter(prefix="/part-requests", tags=["part-requests"])


@router.get("", response_model=list[PartRequest])
def list_part_requests(status: Optional[PartRequestStatus] = None):
    with get_session() as session:
        query = select(PartRequest).order_by(PartRequest.created_at)
        if status is not None:
            query = query.where(PartRequest.status == status)
        return session.exec(query).all()


@router.get("/{request_id}", response_model=PartRequest)
def get_part_request(request_id: int):
    with get_session() as session:
        request = session.get(PartRequest, request_id)
        if not request:
            raise HTTPException(404, f"part request {request_id} not found")
        return request


@router.post("", response_model=PartRequest)
def create_part_request(body: PartRequestCreate):
    with get_session() as session:
        return get_m3_adapter().create_part_request(
            session, body.mechanic, body.tail_number, body.part_number, body.quantity, body.station, datetime.now()
        )


@router.post("/{request_id}/photo", response_model=PartRequest)
def submit_pick_photo(request_id: int, photo: UploadFile = File(...)):
    with get_session() as session:
        request = session.get(PartRequest, request_id)
        if not request:
            raise HTTPException(404, f"part request {request_id} not found")

        try:
            return resolve_pick(session, request, photo.filename or "", datetime.now())
        except PartRequestAlreadyResolved as e:
            raise HTTPException(409, str(e))
