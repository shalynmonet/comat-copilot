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
    pending_verification = "pending_verification"
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
    verification_required = "verification-required"
    verified = "verified"
    phantom_flagged = "phantom-flagged"
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


class ShippingRequestTrigger(str, Enum):
    expiry = "expiry"
    failure = "failure"


class RemovalReason(str, Enum):
    failure = "failure"
    scheduled = "scheduled"
    expiry = "expiry"


class StockingSuggestionStatus(str, Enum):
    pending = "pending"
    approved = "approved"


class ShipmentDraftStatus(str, Enum):
    draft = "draft"
    ready = "ready"
    submitted = "submitted"
    superseded = "superseded"


class VerifyTaskStatus(str, Enum):
    open = "open"
    matched = "matched"
    mismatched = "mismatched"


class PartRequestStatus(str, Enum):
    open = "open"
    picked = "picked"
    issued = "issued"
    flagged = "flagged"


class Station(SQLModel, table=True):
    code: str = Field(primary_key=True)
    name: str
    lat: float
    lon: float
    has_maintenance: bool = False
    stores_capacity: int = 0
    pal_number: Optional[str] = None
    # Share of this station's photo verifications that have turned up a
    # mismatch -- nudged up on every verify_task mismatch (see
    # app/planner/confidence.py), fed back into confidence for every
    # spare at this station.
    discrepancy_rate: float = 0.0


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
    # The shelf-life lot this unit belongs to -- what M3's Expiring Lot
    # Report is keyed by (see app/adapters/m3_adapter.py's
    # get_expiring_lots). Defaults to the serial when a part isn't
    # tracked in distinct lots.
    lot: Optional[str] = None
    # Shelf/bin location within the station -- what a PickSlip tells a
    # mechanic to go find (see app/adapters/m3_adapter.py's
    # get_expected_stock/create_part_request).
    location: Optional[str] = None

    # Inventory confidence: whether the record is likely to match what's
    # actually on the shelf. See app/planner/confidence.py for the
    # formula; confidence here is a cached snapshot, refreshed whenever
    # something that feeds it changes (seeding, a verify_task resolving).
    last_verified_at: Optional[datetime] = None
    verified_by: Optional[str] = None
    move_count_30d: int = 0
    confidence: float = 1.0
    phantom_flag: bool = False


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
    pending_spare_serial: Optional[str] = Field(default=None, foreign_key="inventoryitem.serial")

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

    # The exact inventory row this plan's committed option depends on --
    # only set for COMAT/transfer (a spare), never for buy. Lets the
    # verification gate (app/planner/verification.py) and a later
    # pick-and-issue flow find precisely which record to check or update,
    # rather than re-guessing from option/source.
    spare_serial: Optional[str] = Field(default=None, foreign_key="inventoryitem.serial")


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
    the Stores Queue page.

    serial is usually set (the specific installed part this is about),
    but is None for a station-level restock request -- e.g. Copilot
    flagging that disposing of an expiring lot would leave a station
    with no valid spare at all, with no specific installed part driving
    the need yet (see app/planner/expiring_lots.py)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    part_number: str = Field(foreign_key="part.part_number")
    serial: Optional[str] = Field(default=None, foreign_key="installedpart.serial")
    station_needed: str = Field(foreign_key="station.code")
    needed_by: date
    priority: Priority
    raised_by: RaisedBy
    status: ShippingRequestStatus = ShippingRequestStatus.open
    # expiry (the default) or failure -- most parts are actually replaced
    # on condition or after failure, not on a schedule (see
    # app/planner/failures.py and POST /failures).
    trigger: ShippingRequestTrigger = ShippingRequestTrigger.expiry
    notes: Optional[str] = None  # the write-up, for a failure-triggered request
    plan_id: Optional[int] = Field(default=None, foreign_key="plan.id")
    shipment_draft_id: Optional[int] = Field(default=None, foreign_key="shipmentdraft.id")
    created_at: datetime = Field(default_factory=datetime.now)


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


class VerifyTask(SQLModel, table=True):
    """Raised when a plan's committed option depends on a spare below the
    confidence threshold -- Stores photographs the part tag/data plate to
    confirm it's really there before the plan can proceed. See
    app/planner/verification.py and app/adapters/verify_tag.py."""

    id: Optional[int] = Field(default=None, primary_key=True)
    inventory_serial: str = Field(foreign_key="inventoryitem.serial")
    plan_id: int = Field(foreign_key="plan.id")
    status: VerifyTaskStatus = VerifyTaskStatus.open
    reason: str  # the confidence formula's top reason, e.g. "last verified 62 days ago"
    confidence_at_creation: float
    created_at: datetime
    resolved_at: Optional[datetime] = None
    photo_filename: Optional[str] = None
    extracted_part_number: Optional[str] = None
    extracted_serial: Optional[str] = None
    extracted_condition: Optional[str] = None


class PartRequest(SQLModel, table=True):
    """Digital pick-and-issue: a mechanic's parts list becomes a request,
    the stock clerk picks against M3's expected stock (location +
    serial), and a photo of the shelf tag replaces hand-writing it and
    retyping it into M3. See app/adapters/m3_adapter.py and
    app/planner/pick_issue.py."""

    id: Optional[int] = Field(default=None, primary_key=True)
    mechanic: str
    tail_number: str = Field(foreign_key="aircraft.tail_number")
    part_number: str = Field(foreign_key="part.part_number")
    quantity: int = 1
    station: str = Field(foreign_key="station.code")
    status: PartRequestStatus = PartRequestStatus.open

    # What M3 expected to find, set when the request is created.
    expected_location: Optional[str] = None
    expected_serial: Optional[str] = Field(default=None, foreign_key="inventoryitem.serial")

    # What the photo actually showed, once picked.
    picked_location: Optional[str] = None
    picked_serial: Optional[str] = Field(default=None, foreign_key="inventoryitem.serial")
    photo_filename: Optional[str] = None

    # Set only when status is flagged: why, and where to look instead.
    flagged_reason: Optional[str] = None
    suggested_next: Optional[str] = None

    created_at: datetime
    picked_at: Optional[datetime] = None
    issued_at: Optional[datetime] = None


class ExpiringLotActionType(str, Enum):
    use = "use"
    move = "move"
    replace = "replace"


class ExpiringLotActionStatus(str, Enum):
    pending = "pending"
    approved = "approved"


class ExpiringLotAction(SQLModel, table=True):
    """One row per expiring lot M3's report surfaced, with Copilot's
    recommended action and whether a human has approved it yet. See
    app/planner/expiring_lots.py."""

    id: Optional[int] = Field(default=None, primary_key=True)
    inventory_serial: str = Field(foreign_key="inventoryitem.serial")
    lot: str
    action: ExpiringLotActionType
    reason: str
    status: ExpiringLotActionStatus = ExpiringLotActionStatus.pending
    # Set once approved, for a "move" action -- the resulting transfer plan.
    plan_id: Optional[int] = Field(default=None, foreign_key="plan.id")
    unit_cost: float  # the part's unit cost at creation time, for the "shelf-life value saved" stat
    created_at: datetime
    approved_at: Optional[datetime] = None


class RemovalHistory(SQLModel, table=True):
    """Every part that's come off an aircraft -- failure, scheduled
    maintenance, or expiry -- logged so app/planner/stocking.py can work
    out failure rates per part and fleet type. POST /failures logs one
    for every failure reported; the rest is seeded history standing in
    for however many months of real M3/SCEPTRE removal records a pilot
    would have."""

    id: Optional[int] = Field(default=None, primary_key=True)
    part_number: str = Field(foreign_key="part.part_number")
    fleet_type: str
    station: str = Field(foreign_key="station.code")
    tail_number: str = Field(foreign_key="aircraft.tail_number")
    removed_on: date
    reason: RemovalReason


class StockingSuggestion(SQLModel, table=True):
    """A station that operates a fleet type with a real failure history
    for some part, but doesn't hold a spare of it today. A human
    approves (raises an STD request to position one); see
    app/planner/stocking.py."""

    id: Optional[int] = Field(default=None, primary_key=True)
    part_number: str = Field(foreign_key="part.part_number")
    fleet_type: str
    station: str = Field(foreign_key="station.code")
    failure_count: int
    reason: str
    status: StockingSuggestionStatus = StockingSuggestionStatus.pending
    request_id: Optional[int] = Field(default=None, foreign_key="shippingrequest.id")
    created_at: datetime
    approved_at: Optional[datetime] = None
