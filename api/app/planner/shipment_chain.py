"""The iCargo shipping chain: what runs once a human at Stores submits a
ready shipment draft. Copilot never triggers this on its own -- it's
only reachable by submitting an already-"ready" draft (see
POST /shipments/{id}/submitted).

submit_shipment() calls iCargo's create_shipment -> book -> get_awb,
then plays the tracker through every step for the plan's handoff_route
(plane_side has more steps than to_cargo -- see TRACKER_STEPS), logging
each one as its own plan_event. Since this is a demo with no real
cargo system updating us over hours, the whole chain runs in one call
rather than needing a click per step.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from app.adapters.icargo_adapter import ShipmentRequest, get_cargo_adapter
from app.models import (
    HandoffRoute,
    InstalledPart,
    Part,
    Plan,
    PlanEvent,
    PlanEventType,
    PlanStatus,
    ShipmentDraft,
    ShipmentDraftStatus,
    ShipmentStatus,
)

TRACKER_STEPS: dict[HandoffRoute, list[ShipmentStatus]] = {
    HandoffRoute.plane_side: [
        ShipmentStatus.booked,
        ShipmentStatus.awb_issued,
        ShipmentStatus.load_plan_updated,
        ShipmentStatus.accepted,
        ShipmentStatus.screened,
        ShipmentStatus.loaded,
        ShipmentStatus.delivered,
    ],
    HandoffRoute.to_cargo: [
        ShipmentStatus.booked,
        ShipmentStatus.awb_issued,
        ShipmentStatus.handed_to_cargo,
        ShipmentStatus.delivered,
    ],
}


class NoDraftToSubmit(Exception):
    """The plan has no shipment draft at all -- approve it first."""


class DraftNotReady(Exception):
    """The draft is still missing required fields; Stores needs to fill
    them in (or Copilot needs better data) before it can be submitted."""


def _latest_draft(session: Session, plan_id: int) -> Optional[ShipmentDraft]:
    return session.exec(
        select(ShipmentDraft).where(ShipmentDraft.plan_id == plan_id).order_by(ShipmentDraft.id.desc())
    ).first()


def _step_details(
    flight_number: Optional[str], awb: str, is_dangerous_goods: bool, dg_class: Optional[str]
) -> dict[ShipmentStatus, str]:
    screened = (
        f"screened -- DG exemption details captured (class {dg_class or 'n/a'})"
        if is_dangerous_goods
        else "screened"
    )
    return {
        ShipmentStatus.booked: "cargo space booked" + (f" on {flight_number}" if flight_number else " via Cargo"),
        ShipmentStatus.awb_issued: f"AWB issued: {awb}",
        ShipmentStatus.load_plan_updated: "load plan updated (automatic)",
        ShipmentStatus.accepted: "shipment accepted",
        ShipmentStatus.screened: screened,
        ShipmentStatus.loaded: "loaded onto aircraft",
        ShipmentStatus.handed_to_cargo: "handed to Cargo",
        ShipmentStatus.delivered: "delivered",
    }


def submit_shipment(session: Session, plan: Plan, now: Optional[datetime] = None) -> ShipmentDraft:
    now = now or datetime.now()

    draft = _latest_draft(session, plan.id)
    if not draft:
        raise NoDraftToSubmit(f"plan {plan.id} has no shipment draft yet")
    if draft.status != ShipmentDraftStatus.ready:
        raise DraftNotReady(
            f"draft {draft.id} is {draft.status.value}, not ready "
            f"(missing: {', '.join(draft.missing_fields) or 'nothing listed'})"
        )

    installed = session.get(InstalledPart, plan.installed_serial)
    part = session.get(Part, installed.part_number)

    adapter = get_cargo_adapter()
    request = ShipmentRequest(
        part_number=part.part_number,
        serial=installed.serial,
        weight_lb=part.weight_lb,
        flight_number=plan.flight_number,
        handoff_route=plan.handoff_route.value,
    )
    shipment = adapter.create_shipment(session, request)
    confirmation = adapter.book(session, shipment)
    awb = adapter.get_awb(session, shipment)

    plan.awb_number = awb
    draft.status = ShipmentDraftStatus.submitted
    draft.updated_at = now
    session.add(plan)
    session.add(draft)
    session.add(
        PlanEvent(
            plan_id=plan.id,
            event_type=PlanEventType.shipped,
            created_at=now,
            detail=f"submitted to SAFE/iCargo by Stores -- {confirmation.detail}",
        )
    )

    details = _step_details(plan.flight_number, awb, part.is_dangerous_goods, part.dg_class)
    for step in TRACKER_STEPS[plan.handoff_route]:
        plan.shipment_status = step
        session.add(plan)
        session.add(
            PlanEvent(plan_id=plan.id, event_type=PlanEventType.shipped, created_at=now, detail=details[step])
        )

    plan.status = PlanStatus.shipped
    session.add(plan)

    session.commit()
    session.refresh(plan)
    session.refresh(draft)
    return draft
