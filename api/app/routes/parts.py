import os
from datetime import date

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.adapters.sceptre_adapter import get_parts_adapter
from app.db import get_session
from app.models import Part
from app.schemas import ExpiringPartOut

DEFAULT_WINDOW_DAYS = int(os.environ.get("EXPIRY_WINDOW_DAYS", 7))

router = APIRouter(prefix="/parts", tags=["parts"])


@router.get("/catalog", response_model=list[Part])
def list_catalog():
    with get_session() as session:
        return session.exec(select(Part)).all()


@router.get("/catalog/{part_number}", response_model=Part)
def get_part(part_number: str):
    with get_session() as session:
        part = session.get(Part, part_number)
        if not part:
            raise HTTPException(404, f"part {part_number} not found")
        return part


@router.get("/expiring", response_model=list[ExpiringPartOut])
def expiring_parts(window_days: int = DEFAULT_WINDOW_DAYS):
    today = date.today()
    with get_session() as session:
        adapter = get_parts_adapter()
        records = adapter.list_expiring(session, window_days, today)
        return [
            ExpiringPartOut(
                serial=r.serial,
                part_number=r.part_number,
                description=r.description,
                tail_number=r.tail_number,
                station=r.station,
                position=r.position,
                expires_on=r.expires_on,
                days_left=(r.expires_on - today).days,
            )
            for r in records
        ]
