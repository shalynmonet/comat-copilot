"""Tables for the COMAT Copilot data model (see docs/spec.md)."""

from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class InventoryCondition(str, Enum):
    serviceable = "serviceable"
    unserviceable = "unserviceable"
    quarantined = "quarantined"


class PlanOption(str, Enum):
    comat = "COMAT"
    transfer = "transfer"
    buy = "buy"


class PlanStatus(str, Enum):
    proposed = "proposed"
    approved = "approved"
    at_risk = "at_risk"
    re_routed = "re_routed"
    shipped = "shipped"
    installed = "installed"
    cancelled = "cancelled"


class FlightStatus(str, Enum):
    scheduled = "scheduled"
    delayed = "delayed"
    departed = "departed"
    arrived = "arrived"
    cancelled = "cancelled"


class PlanEventType(str, Enum):
    created = "created"
    re_routed = "re-routed"
    approved = "approved"
    overridden = "overridden"
    shipped = "shipped"
    installed = "installed"


class OverrideReason(str, Enum):
    flight_usually_full = "flight_usually_full"
    preferred_vendor = "preferred_vendor"
    spare_needed_elsewhere = "spare_needed_elsewhere"
    other = "other"


OVERRIDE_REASON_LABELS = {
    OverrideReason.flight_usually_full: "that flight usually runs full",
    OverrideReason.preferred_vendor: "preferred vendor",
    OverrideReason.spare_needed_elsewhere: "spare needed elsewhere",
    OverrideReason.other: "other",
}


class Station(SQLModel, table=True):
    code: str = Field(primary_key=True)
    name: str
    lat: float
    lon: float
    has_maintenance: bool = False
    stores_capacity: int = 0


class Aircraft(SQLModel, table=True):
    tail_number: str = Field(primary_key=True)
    type: str
    current_station: str = Field(foreign_key="station.code")
    overnight_station: str = Field(foreign_key="station.code")


class Part(SQLModel, table=True):
    part_number: str = Field(primary_key=True)
    description: str
    shelf_life_days: int
    is_rotable: bool = False
    unit_cost: float
    weight_lb: float
    is_dangerous_goods: bool = False


class InstalledPart(SQLModel, table=True):
    serial: str = Field(primary_key=True)
    part_number: str = Field(foreign_key="part.part_number")
    tail_number: str = Field(foreign_key="aircraft.tail_number")
    position: str
    installed_on: date
    expires_on: date
    hours_remaining: Optional[float] = None


class InventoryItem(SQLModel, table=True):
    serial: str = Field(primary_key=True)
    part_number: str = Field(foreign_key="part.part_number")
    station: str = Field(foreign_key="station.code")
    condition: InventoryCondition
    expires_on: date
    last_counted_on: date


class Flight(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    flight_number: str
    tail_number: str = Field(foreign_key="aircraft.tail_number")
    origin: str = Field(foreign_key="station.code")
    dest: str = Field(foreign_key="station.code")
    sched_dep: datetime
    sched_arr: datetime
    status: FlightStatus = FlightStatus.scheduled
    cargo_capacity_lb: float


class VendorQuote(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    vendor: str
    part_number: str = Field(foreign_key="part.part_number")
    price: float
    lead_time_hrs: float
    ship_to_station: str = Field(foreign_key="station.code")
    certs: str


class Plan(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    installed_serial: str = Field(foreign_key="installedpart.serial")
    option: PlanOption
    source: Optional[str] = None
    flight_number: Optional[str] = None
    cost: float
    risk_score: float
    status: PlanStatus = PlanStatus.proposed
    reason: Optional[str] = None

    # Set when a flight change puts an already-*approved* plan at risk: the
    # system's new recommendation waits here rather than silently overwriting
    # the committed option, since a human already signed off on that one.
    # POST /plans/{id}/approve applies these (and clears them) when present.
    pending_option: Optional[PlanOption] = None
    pending_source: Optional[str] = None
    pending_flight_number: Optional[str] = None
    pending_cost: Optional[float] = None
    pending_risk_score: Optional[float] = None
    pending_reason: Optional[str] = None


class PlanEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="plan.id")
    event_type: PlanEventType
    created_at: datetime
    detail: Optional[str] = None
