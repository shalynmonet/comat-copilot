"""Expiring-lot recommendations, driven by M3's own Expiring Lot Report
(app/adapters/m3_adapter.py's get_expiring_lots) rather than a shelf-life
tracker of our own.

scan_expiring_lots() is the scheduled job (configurable, default daily --
see app/config.py's settings.yaml): for every lot the report surfaces
that Copilot hasn't already recommended something for, it works out one
of three actions --

  use: a known upcoming need at the same station -- reserve the lot.
  move: another station needs it before it expires -- propose an STD
    COMAT transfer through the normal plan flow (build_candidates ->
    approve_plan), so it gets priority/route/draft and real plan_events
    exactly like any other plan.
  replace: no demand in time -- flag it for disposal. If that would
    leave the station with no valid spare, Copilot raises a request for
    one immediately, the same way the expiry scan does.

A human still approves each recommendation (approve_lot_action) before
anything happens -- scanning only proposes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from app.adapters.m3_adapter import StockRecord, get_m3_adapter
from app.models import (
    ExpiringLotAction,
    ExpiringLotActionStatus,
    ExpiringLotActionType,
    InstalledPart,
    InventoryCondition,
    InventoryItem,
    Part,
    Priority,
    RaisedBy,
    ShippingRequest,
    ShippingRequestStatus,
)
from app.planner.candidates import build_candidates, deadline_for
from app.planner.decisions import approve_plan
from app.planner.intake import link_request_to_plan
from app.planner.score import pick_best, to_plan


class ExpiringLotActionAlreadyResolved(Exception):
    """The action was already approved -- approving only happens once."""


_OPEN_REQUEST_STATUSES = [ShippingRequestStatus.open, ShippingRequestStatus.planned]


def _recommend(session: Session, lot: StockRecord, now: datetime) -> tuple[ExpiringLotActionType, str]:
    same_station_need = session.exec(
        select(ShippingRequest).where(
            ShippingRequest.part_number == lot.part_number,
            ShippingRequest.station_needed == lot.station,
            ShippingRequest.status.in_(_OPEN_REQUEST_STATUSES),
        )
    ).first()
    if same_station_need:
        return (
            ExpiringLotActionType.use,
            f"a known need at {lot.station} (request #{same_station_need.id}) can use this lot before it expires",
        )

    other_station_need = session.exec(
        select(ShippingRequest).where(
            ShippingRequest.part_number == lot.part_number,
            ShippingRequest.station_needed != lot.station,
            ShippingRequest.status.in_(_OPEN_REQUEST_STATUSES),
            ShippingRequest.needed_by <= lot.expires_on,
        )
    ).first()
    if other_station_need:
        return (
            ExpiringLotActionType.move,
            f"{other_station_need.station_needed} needs this part by {other_station_need.needed_by}, "
            "before it expires here",
        )

    others = [
        r
        for r in get_m3_adapter().list_stock(session, part_number=lot.part_number, station=lot.station)
        if r.serial != lot.serial and r.condition == InventoryCondition.serviceable and r.expires_on > lot.expires_on
    ]
    if others:
        return (
            ExpiringLotActionType.replace,
            "no upcoming demand before it expires -- flagged for disposal; another valid spare remains at this station",
        )

    # No demand, and no other spare at this station either -- Copilot
    # raises a station-level restock request now (no specific installed
    # part drives it, so serial is left unset).
    session.add(
        ShippingRequest(
            part_number=lot.part_number,
            serial=None,
            station_needed=lot.station,
            needed_by=lot.expires_on,
            priority=Priority.std,
            raised_by=RaisedBy.copilot,
            status=ShippingRequestStatus.open,
        )
    )
    return (
        ExpiringLotActionType.replace,
        "no upcoming demand before it expires and no other valid spare remains at this station -- "
        "flagged for disposal and a replacement request raised",
    )


def scan_expiring_lots(session: Session, window_days: int, now: Optional[datetime] = None) -> list[ExpiringLotAction]:
    now = now or datetime.now()
    already = {
        (a.inventory_serial, a.lot) for a in session.exec(select(ExpiringLotAction)).all()
    }

    created: list[ExpiringLotAction] = []
    for lot in get_m3_adapter().get_expiring_lots(session, window_days):
        if (lot.serial, lot.lot) in already:
            continue
        action_type, reason = _recommend(session, lot, now)
        part = session.get(Part, lot.part_number)
        record = ExpiringLotAction(
            inventory_serial=lot.serial,
            lot=lot.lot,
            action=action_type,
            reason=reason,
            unit_cost=part.unit_cost if part else 0.0,
            created_at=now,
        )
        session.add(record)
        created.append(record)

    session.commit()
    for record in created:
        session.refresh(record)
    return created


def approve_lot_action(session: Session, action: ExpiringLotAction, now: Optional[datetime] = None) -> ExpiringLotAction:
    now = now or datetime.now()
    if action.status != ExpiringLotActionStatus.pending:
        raise ExpiringLotActionAlreadyResolved(f"expiring-lot action {action.id} is already {action.status.value}")

    if action.action == ExpiringLotActionType.move:
        # Re-derive the specific request this action was recommended for --
        # the one needing this lot's part at a station other than where
        # the lot sits, with no plan yet.
        item = session.get(InventoryItem, action.inventory_serial)
        request = session.exec(
            select(ShippingRequest).where(
                ShippingRequest.part_number == item.part_number,
                ShippingRequest.station_needed != item.station,
                ShippingRequest.status.in_(_OPEN_REQUEST_STATUSES),
                ShippingRequest.plan_id.is_(None),
            )
        ).first()
        if request:
            installed = session.get(InstalledPart, request.serial)
            candidates = build_candidates(session, installed, now=now)
            best = pick_best(candidates, deadline=deadline_for(installed))
            if best:
                plan = to_plan(installed.serial, best)
                session.add(plan)
                session.commit()
                session.refresh(plan)
                plan = approve_plan(session, plan, now=now)
                link_request_to_plan(session, installed.serial, plan.id)
                session.commit()
                action.plan_id = plan.id

    action.status = ExpiringLotActionStatus.approved
    action.approved_at = now
    session.add(action)
    session.commit()
    session.refresh(action)
    return action
