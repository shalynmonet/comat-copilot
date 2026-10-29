"""Tables for the COMAT Copilot data model (see docs/spec.md)."""

from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlalchemy import JSON, Column
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
    draft_created = "draft-created"
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


class Priority(str, Enum):
    aog = "AOG"  # aircraft on ground -- no feasible backup remains
    mrd = "MRD"  # Must Ride: guaranteed space, cannot be bumped
    mrx = "MRX"  # lower priority, always routed via Cargo; never auto-assigned
    std = "STD"  # standard: can be bumped if there's no space


class CommodityProfile(str, Enum):
    """The generic profile names used in code; api/config/private_codes.yaml
    maps each one to its real handoff route and handling codes."""

    critical_planeside = "critical_planeside"
    critical_cargo = "critical_cargo"
    low_cargo = "low_cargo"


class HandoffRoute(str, Enum):
    plane_side = "plane_side"
    to_cargo = "to_cargo"


class ShipmentStatus(str, Enum):
    """Tracker steps. plane_side plans pass through all of these;
    to_cargo plans only use booked, awb_issued, handed_to_cargo, delivered."""

    booked = "booked"
    awb_issued = "awb_issued"
    load_plan_updated = "load_plan_updated"
    accepted = "accepted"
    screened = "screened"
    loaded = "loaded"
    handed_to_cargo = "handed_to_cargo"
    delivered = "delivered"


class RaisedBy(str, Enum):
    maintenance_control = "maintenance_control"
    stores = "stores"
    copilot = "copilot"


class ShippingRequestStatus(str, Enum):
    open = "open"
    planned = "planned"
    drafted = "drafted"
    submitted = "submitted"
    fulfilled = "fulfilled"
    cancelled = "cancelled"


class ShipmentDraftStatus(str, Enum):
    draft = "draft"
    ready = "ready"
    submitted = "submitted"
    superseded = "superseded"


class Station(SQLModel, table=True):
    code: str = Field(primary_key=True)
    name: str
    lat: float
    lon: float
    has_maintenance: bool = False
    stores_capacity: int = 0
    pal_number: Optional[str] = None


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
    dg_class: Optional[str] = None
    is_oversize: bool = False


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
    accepts_dg: bool = False
    is_international: bool = False


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

    # Shipping: priority/profile/route the planner assigned, and the
    # resulting shipment's tracked state. See app/config.py for what each
    # commodity_profile actually means (route + handling codes).
    priority: Optional[Priority] = None
    commodity_profile: Optional[CommodityProfile] = None
    handling_codes: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    handoff_route: Optional[HandoffRoute] = None
    is_ron_package: bool = False  # part is being replaced during an overnight stay
    awb_number: Optional[str] = None
    shipment_status: Optional[ShipmentStatus] = None

    # Set when a flight was booked inside the booking cutoff via an
    # explicit AOG-desk override, bypassing the normal 60/90-minute rule.
    aog_desk_override: bool = False
    aog_desk_override_by: Optional[str] = None
    override_reason: Optional[str] = None


class PlanEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="plan.id")
    event_type: PlanEventType
    created_at: datetime
    detail: Optional[str] = None


class ShippingRequest(SQLModel, table=True):
    """Raised as soon as a part is known to be expiring -- by Copilot's own
    scan, maintenance control, or Stores -- so Stores can review and submit
    instead of retyping from scratch. See app/adapters/safe_adapter.py and
    the Stores Queue page."""

    id: Optional[int] = Field(default=None, primary_key=True)
    part_number: str = Field(foreign_key="part.part_number")
    serial: str = Field(foreign_key="installedpart.serial")
    station_needed: str = Field(foreign_key="station.code")
    needed_by: date
    priority: Priority
    raised_by: RaisedBy
    status: ShippingRequestStatus = ShippingRequestStatus.open
    plan_id: Optional[int] = Field(default=None, foreign_key="plan.id")
    shipment_draft_id: Optional[int] = Field(default=None, foreign_key="shipmentdraft.id")


class ShipmentDraft(SQLModel, table=True):
    """A SAFE-ready shipment, pre-filled from a plan. `fields` holds the
    actual SAFE field values (see api/app/adapters/safe_fields.yaml for the
    field list); `missing_fields` lists any required field that couldn't be
    filled, which is what keeps status at "draft" instead of "ready"."""

    id: Optional[int] = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="plan.id")
    fields: dict = Field(default_factory=dict, sa_column=Column(JSON))
    status: ShipmentDraftStatus = ShipmentDraftStatus.draft
    missing_fields: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime
    updated_at: datetime
