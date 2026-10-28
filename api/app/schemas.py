"""Request/response shapes that aren't DB tables."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel

from app.models import PlanOption


class ExpiringPartOut(BaseModel):
    serial: str
    part_number: str
    description: str
    tail_number: str
    station: str
    position: str
    expires_on: date
    days_left: int


class CandidateOut(BaseModel):
    option: PlanOption
    source: str
    flight_number: Optional[str]
    cost: float
    eta: datetime
    risk_score: float
    score: float
    detail: str


class PlanCreateRequest(BaseModel):
    installed_serial: str


class DelayRequest(BaseModel):
    minutes: int = 180
