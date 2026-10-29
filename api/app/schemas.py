"""Request/response shapes that aren't DB tables."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel

from app.models import OverrideReason, PlanOption


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
    risk_score: Optional[float]
    score: Optional[float]
    detail: str
    disqualified: bool = False
    disqualified_reason: Optional[str] = None
    is_dangerous_goods: bool = False


class PlanCreateRequest(BaseModel):
    installed_serial: str


class DelayRequest(BaseModel):
    minutes: int = 180


class ChoosePlanRequest(BaseModel):
    """The body for POST /plans/{id}/choose -- a human picking a feasible
    candidate other than the system's top recommendation, and saying why."""

    option: PlanOption
    source: str
    flight_number: Optional[str] = None
    reason: OverrideReason
    note: Optional[str] = None


class FieldSpecOut(BaseModel):
    """A SAFE field's name/label/required-ness, so the frontend can render
    field labels (e.g. for "Copy to SAFE") without duplicating
    safe_fields.yaml."""

    name: str
    label: str
    required: bool
