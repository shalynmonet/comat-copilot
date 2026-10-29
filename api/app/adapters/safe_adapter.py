"""SAFE-ready shipment draft adapter.

Stores receives shipping requests in SAFE and creates shipments by hand
today. This adapter pre-fills every field SAFE would need from a plan,
so Stores reviews and submits instead of retyping -- Copilot never
submits to SAFE itself.

The field list (name, label, required) lives in
api/app/adapters/safe_fields.yaml, so the real SAFE field names can be
swapped in later without touching this code. build_draft() below is
where each field's *value* is computed -- kept as explicit code rather
than a generic dotted-path resolver, so a wrong mapping fails a test
loudly instead of silently through a typo'd path string.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sqlmodel import Session, select

from app.models import Aircraft, Flight, InstalledPart, Part, Plan, PlanOption, Station

FIELDS_PATH = Path(__file__).parent / "safe_fields.yaml"


@dataclass
class SafeFieldSpec:
    name: str
    label: str
    source: str
    required: bool


@dataclass
class DraftResult:
    fields: dict[str, Any]
    missing_fields: list[str]
    status: str  # "draft" | "ready"


def load_field_specs() -> list[SafeFieldSpec]:
    raw = yaml.safe_load(FIELDS_PATH.read_text())
    return [SafeFieldSpec(**f) for f in raw["fields"]]


def _condition_for(option: PlanOption) -> str:
    # Only serviceable spares ever become feasible COMAT/transfer
    # candidates (see planner/candidates.py); a buy is vendor-new stock.
    return "new" if option == PlanOption.buy else "serviceable"


def _is_missing(value: Any) -> bool:
    return value is None or value == "" or value == []


def build_draft(session: Session, plan: Plan) -> DraftResult:
    installed = session.get(InstalledPart, plan.installed_serial)
    part = session.get(Part, installed.part_number)
    aircraft = session.get(Aircraft, installed.tail_number)

    flight = None
    if plan.flight_number:
        flight = session.exec(select(Flight).where(Flight.flight_number == plan.flight_number)).first()

    # plan.source is a station code for COMAT/transfer, but a vendor name
    # for buy -- only look it up as a station in the former case. PALs
    # legitimately can't be filled for a vendor purchase, which correctly
    # keeps a buy-sourced draft's status at "draft".
    origin_station = None
    if plan.option in (PlanOption.comat, PlanOption.transfer) and plan.source:
        origin_station = session.get(Station, plan.source)
    dest_station = session.get(Station, aircraft.overnight_station)

    values: dict[str, Any] = {
        "part_number": part.part_number,
        "serial": installed.serial,
        "description": part.description,
        "quantity": 1,
        "condition": _condition_for(plan.option),
        "origin_station": origin_station.code if origin_station else plan.source,
        "dest_station": dest_station.code if dest_station else None,
        "flight_legs": [plan.flight_number] if plan.flight_number else [],
        "flight_date": flight.sched_dep.isoformat() if flight else None,
        "tail_number": installed.tail_number,
        "priority": plan.priority.value if plan.priority else None,
        "commodity_profile": plan.commodity_profile.value if plan.commodity_profile else None,
        "handling_codes": list(plan.handling_codes or []),
        "handoff_route": plan.handoff_route.value if plan.handoff_route else None,
        "is_dangerous_goods": part.is_dangerous_goods,
        "dg_class": part.dg_class,
        "weight_lb": part.weight_lb,
        "agent_pal": origin_station.pal_number if origin_station else None,
        "shipper_pal": origin_station.pal_number if origin_station else None,
        "consignee_pal": dest_station.pal_number if dest_station else None,
        "awb_number": plan.awb_number,
        "requested_by": "COMAT Copilot",
        "notes": plan.reason,
    }

    specs = load_field_specs()
    missing = [spec.name for spec in specs if spec.required and _is_missing(values.get(spec.name))]
    status = "draft" if missing else "ready"
    return DraftResult(fields=values, missing_fields=missing, status=status)
