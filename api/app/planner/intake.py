"""Intake: raising shipping requests from the expiry scan, suggesting a
source/flight/route for the Stores Queue to show before anyone has
approved anything, and the dashboard's "avoided" stats.

Copilot raises a request the moment a part enters the expiry window --
as early as possible -- rather than waiting for it to become urgent.
That's the whole pitch: catching it early turns what would've been an
AOG or a rushed plane-side run into an ordinary STD shipment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from app.adapters.sceptre_adapter import get_parts_adapter
from app.models import (
    CommodityProfile,
    HandoffRoute,
    InstalledPart,
    Part,
    Plan,
    PlanOption,
    PlanStatus,
    Priority,
    RaisedBy,
    ShippingRequest,
    ShippingRequestStatus,
)
from app.planner.candidates import build_candidates, deadline_for
from app.planner.priority_rules import compute_priority_assignment
from app.planner.score import pick_best


@dataclass
class PartSuggestion:
    """What the planner would currently recommend for an expiring part --
    read-only, nothing is created or approved. Shown on the Stores Queue
    so a planner can see the suggested source/flight/route before any
    plan exists."""

    installed_serial: str
    option: Optional[PlanOption]
    source: Optional[str]
    flight_number: Optional[str]
    cost: Optional[float]
    priority: Priority
    commodity_profile: Optional[CommodityProfile]
    handoff_route: Optional[HandoffRoute]
    reason: str


def suggest_for_part(session: Session, installed: InstalledPart, now: datetime) -> PartSuggestion:
    part = session.get(Part, installed.part_number)
    deadline = deadline_for(installed)
    candidates = build_candidates(session, installed, now=now)
    best = pick_best(candidates, deadline)

    if best is None:
        part_expired = installed.expires_on < now.date()
        return PartSuggestion(
            installed_serial=installed.serial,
            option=None,
            source=None,
            flight_number=None,
            cost=None,
            priority=Priority.aog,
            commodity_profile=None,
            handoff_route=None,
            reason="the part has already expired" if part_expired else "no feasible option remains before the deadline",
        )

    assignment = compute_priority_assignment(
        session, installed, part, best.candidate.option, best.candidate.source,
        best.candidate.flight_number, is_ron_package=False, now=now,
    )
    return PartSuggestion(
        installed_serial=installed.serial,
        option=best.candidate.option,
        source=best.candidate.source,
        flight_number=best.candidate.flight_number,
        cost=best.candidate.cost,
        priority=assignment.priority,
        commodity_profile=assignment.commodity_profile,
        handoff_route=assignment.handoff_route,
        reason=best.candidate.detail,
    )


def raise_copilot_requests(session: Session, window_days: int, now: datetime) -> list[ShippingRequest]:
    """Scans expiring parts (via the Sceptre adapter) and raises a
    ShippingRequest, raised_by=copilot, for each one that doesn't already
    have an open request -- from Copilot or anyone else. Idempotent:
    calling this repeatedly never raises a duplicate for the same part.
    """
    adapter = get_parts_adapter()
    records = adapter.list_expiring(session, window_days, now.date())

    already_requested = {
        r.serial
        for r in session.exec(
            select(ShippingRequest).where(ShippingRequest.status != ShippingRequestStatus.cancelled)
        ).all()
    }

    raised = []
    for record in records:
        if record.serial in already_requested:
            continue
        installed = session.get(InstalledPart, record.serial)
        if not installed:
            continue
        suggestion = suggest_for_part(session, installed, now)
        request = ShippingRequest(
            part_number=record.part_number,
            serial=record.serial,
            station_needed=record.station,
            needed_by=record.expires_on,
            priority=suggestion.priority,
            raised_by=RaisedBy.copilot,
            status=ShippingRequestStatus.open,
        )
        session.add(request)
        raised.append(request)

    session.commit()
    for request in raised:
        session.refresh(request)
    return raised


def link_request_to_plan(session: Session, installed_serial: str, plan_id: int) -> Optional[ShippingRequest]:
    """Called once a Plan exists for a part: if there's an open request
    for it (from Copilot or anyone else), attach the plan so the request
    can be tracked through to fulfillment and counted in the avoided
    stats. No-op if there's no open request -- not every plan started
    from a request."""
    request = session.exec(
        select(ShippingRequest).where(
            ShippingRequest.serial == installed_serial,
            ShippingRequest.status == ShippingRequestStatus.open,
        )
    ).first()
    if not request:
        return None
    request.plan_id = plan_id
    request.status = ShippingRequestStatus.planned
    session.add(request)
    return request


@dataclass
class AvoidedStats:
    aogs_avoided: int
    planeside_runs_avoided: int


def compute_avoided_stats(session: Session) -> AvoidedStats:
    """Copilot-raised requests that reached a fulfilled plan while still
    STD / low_cargo -- i.e. the part never actually became an AOG, and
    never needed a rushed plane-side run, because Copilot caught it
    early. "Turn AOGs into STDs."
    """
    requests = session.exec(select(ShippingRequest).where(ShippingRequest.raised_by == RaisedBy.copilot)).all()

    aogs_avoided = 0
    planeside_avoided = 0
    for request in requests:
        if not request.plan_id:
            continue
        plan = session.get(Plan, request.plan_id)
        if not plan or plan.status not in (PlanStatus.shipped, PlanStatus.installed):
            continue
        if plan.priority == Priority.std:
            aogs_avoided += 1
        if plan.commodity_profile == CommodityProfile.low_cargo:
            planeside_avoided += 1

    return AvoidedStats(aogs_avoided=aogs_avoided, planeside_runs_avoided=planeside_avoided)
