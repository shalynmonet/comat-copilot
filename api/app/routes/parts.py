import os
from datetime import date

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.db import get_session
from app.models import Aircraft, InstalledPart, Part
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
        installed = session.exec(select(InstalledPart)).all()
        parts_by_number = {p.part_number: p for p in session.exec(select(Part)).all()}
        aircraft_by_tail = {a.tail_number: a for a in session.exec(select(Aircraft)).all()}

        out = []
        for ip in installed:
            days_left = (ip.expires_on - today).days
            if days_left > window_days:
                continue
            part = parts_by_number.get(ip.part_number)
            aircraft = aircraft_by_tail.get(ip.tail_number)
            out.append(
                ExpiringPartOut(
                    serial=ip.serial,
                    part_number=ip.part_number,
                    description=part.description if part else "",
                    tail_number=ip.tail_number,
                    station=aircraft.overnight_station if aircraft else "",
                    position=ip.position,
                    expires_on=ip.expires_on,
                    days_left=days_left,
                )
            )
        out.sort(key=lambda p: p.days_left)
        return out
