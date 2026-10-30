"""Request/response shapes that aren't DB tables."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel

from app.models import OverrideReason, PlanOption, RaisedBy


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
    spare_serial: Optional[str] = None
    confidence: Optional[float] = None
    low_confidence_reason: Optional[str] = None


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


class PartRequestCreate(BaseModel):
    """The body for POST /part-requests -- what a mechanic's parts list
    turns into once the stock clerk opens a pick."""

    mechanic: str
    tail_number: str
    part_number: str
    quantity: int = 1
    station: str


class FailureReportCreate(BaseModel):
    """The body for POST /failures -- a write-up that immediately runs
    the planner (see app/planner/failures.py)."""

    tail_number: str
    station: str
    part_number: str
    reported_by: RaisedBy
    notes: Optional[str] = None


class StationDiscrepancyOut(BaseModel):
    station: str
    discrepancy_rate: float


class DashboardStatsOut(BaseModel):
    """Everything the dashboard's stats strip shows, in one call: Copilot's
    "turn AOGs into STDs" impact (see app/planner/intake.py), and
    inventory-confidence impact (phantom parts a photo verify caught
    before they caused an AOG, and each station's discrepancy track
    record -- see app/planner/confidence.py)."""

    aogs_avoided: int
    planeside_runs_avoided: int
    phantom_parts_caught: int
    station_discrepancy_rates: list[StationDiscrepancyOut]
    picks_verified_by_photo: int
    discrepancies_caught_at_pick: int
    shelf_life_value_saved: float
    failure_response_time_median_minutes: Optional[float]
