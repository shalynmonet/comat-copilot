from fastapi import APIRouter
from sqlmodel import select

from app.db import get_session
from app.models import Station

router = APIRouter(prefix="/stations", tags=["stations"])


@router.get("", response_model=list[Station])
def list_stations():
    with get_session() as session:
        return session.exec(select(Station)).all()
