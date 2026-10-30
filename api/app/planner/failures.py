"""Unscheduled failures: most parts are actually replaced on condition or
after a write-up, not on a schedule, so this is the fast path -- a
failure immediately runs the full planner (nearest valid spare, fastest
bookable flight with cutoffs/connections/DG rules, priority by the
backup-flight rule, profile/route, a pre-filled SAFE draft) instead of
waiting for Copilot's own expiry scan to notice anything.

The one place a failure's planning differs from the normal flow: if the
best candidate's spare is below the confidence threshold, there may not
be time for a Stores photo verify before that flight's own booking
cutoff. When there is, the normal verify_task gate still applies
(finish_approval handles that). When there isn't, this skips straight
to the next valid candidate instead -- saying why in the plan's reason
line -- rather than stalling the response on a verification nobody has
time to do.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlmodel import Session, select

from app.config import load_private_codes, load_settings
from app.models import (
    Aircraft,
    Flight,
    InstalledPart,
    Plan,
    Priority,
    RaisedBy,
    RemovalHistory,
    RemovalReason,
    ShipmentDraft,
    ShipmentDraftStatus,
    ShippingRequest,
    ShippingRequestStatus,
    ShippingRequestTrigger,
)
from app.planner.candidates import build_candidates, deadline_for
from app.planner.score import rank_candidates, to_plan
from app.planner.verification import finish_approval


class NoInstalledPartForFailure(Exception):
    """No installed part matches the tail/part_number a failure was reported against."""


def _cutoff_slack_minutes(session: Session, flight_number: str, now: datetime) -> Optional[float]:
    """Minutes between now and the first leg's own booking cutoff moment
    -- None if that flight can't be found (treated as "plenty of time",
    e.g. for a ground transfer or buy, which have no flight cutoff at all)."""
    first_leg = flight_number.split("/")[0]
    flight = session.exec(select(Flight).where(Flight.flight_number == first_leg)).first()
    if not flight:
        return None
    codes = load_private_codes()
    cutoff_minutes = (
        codes.booking_cutoff_minutes_international if flight.is_international else codes.booking_cutoff_minutes_domestic
    )
    cutoff_moment = flight.sched_dep - timedelta(minutes=cutoff_minutes)
    return (cutoff_moment - now).total_seconds() / 60


def plan_for_failure(session: Session, installed: InstalledPart, now: datetime) -> Optional[Plan]:
    deadline = deadline_for(installed)
    candidates = build_candidates(session, installed, now=now)
    ranked = rank_candidates(candidates, deadline)

    threshold = load_settings().confidence.verification_threshold
    buffer_minutes = load_settings().failures.verify_time_buffer_minutes

    chosen = None
    skip_notes: list[str] = []
    for scored in ranked:
        c = scored.candidate
        if c.confidence is not None and c.confidence < threshold and c.flight_number:
            slack = _cutoff_slack_minutes(session, c.flight_number, now)
            if slack is not None and slack < buffer_minutes:
                skip_notes.append(
                    f"skipped {c.source} (confidence {c.confidence:.2f}, no time to verify before cutoff)"
                )
                continue
        chosen = scored
        break

    if chosen is None:
        if not ranked:
            return None
        chosen = ranked[0]  # nothing with enough time -- fall back to the best overall

    plan = to_plan(installed.serial, chosen)
    if skip_notes:
        plan.reason = f"{plan.reason} -- {'; '.join(skip_notes)}"
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return finish_approval(session, plan, now)


def report_failure(
    session: Session,
    tail_number: str,
    station: str,
    part_number: str,
    raised_by: RaisedBy,
    notes: Optional[str],
    now: Optional[datetime] = None,
) -> tuple[ShippingRequest, Optional[Plan]]:
    now = now or datetime.now()
    installed = session.exec(
        select(InstalledPart).where(
            InstalledPart.tail_number == tail_number, InstalledPart.part_number == part_number
        )
    ).first()
    if not installed:
        raise NoInstalledPartForFailure(f"no installed {part_number} found on {tail_number}")

    aircraft = session.get(Aircraft, tail_number)
    plan = plan_for_failure(session, installed, now)

    request = ShippingRequest(
        part_number=part_number,
        serial=installed.serial,
        station_needed=station,
        needed_by=now.date(),
        priority=plan.priority if plan and plan.priority else Priority.aog,
        raised_by=raised_by,
        status=ShippingRequestStatus.planned if plan else ShippingRequestStatus.open,
        trigger=ShippingRequestTrigger.failure,
        notes=notes,
        plan_id=plan.id if plan else None,
        created_at=now,
    )
    session.add(request)
    session.add(
        RemovalHistory(
            part_number=part_number,
            fleet_type=aircraft.type if aircraft else "unknown",
            station=station,
            tail_number=tail_number,
            removed_on=now.date(),
            reason=RemovalReason.failure,
        )
    )
    session.commit()
    session.refresh(request)
    if plan:
        session.refresh(plan)  # the request's own commit just expired it
    return request, plan


def compute_failure_response_time_median_minutes(session: Session) -> Optional[float]:
    """Median minutes from a failure write-up (ShippingRequest.created_at)
    to its shipment being booked (the resulting draft reaching
    "submitted") -- None until at least one has completed that path."""
    requests = session.exec(
        select(ShippingRequest).where(
            ShippingRequest.trigger == ShippingRequestTrigger.failure, ShippingRequest.plan_id.is_not(None)
        )
    ).all()

    durations: list[float] = []
    for r in requests:
        draft = session.exec(
            select(ShipmentDraft).where(
                ShipmentDraft.plan_id == r.plan_id, ShipmentDraft.status == ShipmentDraftStatus.submitted
            )
        ).first()
        if draft:
            durations.append((draft.updated_at - r.created_at).total_seconds() / 60)

    if not durations:
        return None
    durations.sort()
    mid = len(durations) // 2
    if len(durations) % 2 == 1:
        return durations[mid]
    return (durations[mid - 1] + durations[mid]) / 2
