"""Human decisions on a plan: approving the current (or a flight-change's
staged pending) recommendation, or overriding it with a different feasible
option and saying why. Kept separate from routes/plans.py, and from
replan.py's automated recalculation, so each is unit-testable on its own.
"""

from datetime import datetime
from typing import Optional

from sqlmodel import Session

from app.adapters.icargo_adapter import BookingRequest, CargoBookingError, get_cargo_adapter
from app.adapters.shipping_adapter import ShippingTicketRequest, get_shipping_adapter
from app.models import (
    OVERRIDE_REASON_LABELS,
    Aircraft,
    InstalledPart,
    OverrideReason,
    Part,
    Plan,
    PlanEvent,
    PlanEventType,
    PlanOption,
    PlanStatus,
)
from app.planner.candidates import build_candidates, deadline_for
from app.planner.score import score_candidate


class NoSuchCandidate(Exception):
    """Raised when the chosen (option, source, flight_number) no longer
    matches a feasible candidate -- e.g. it was overtaken by events between
    the browser fetching candidates and the human clicking a button."""


def clear_pending(plan: Plan) -> None:
    plan.pending_option = None
    plan.pending_source = None
    plan.pending_flight_number = None
    plan.pending_cost = None
    plan.pending_risk_score = None
    plan.pending_reason = None


def _fulfill_approved_plan(session: Session, plan: Plan) -> None:
    """Runs the paperwork for an approved plan: a COMAT option holds real
    cargo space via iCargo, and every option gets a shipping ticket / work
    order via the shipping system -- the two artifacts the demo script
    calls out ("a work order and shipping ticket generate"). Logged as one
    "shipped" plan_event. A failed booking is logged, never blocking.
    """
    installed = session.get(InstalledPart, plan.installed_serial)
    part = session.get(Part, installed.part_number)
    aircraft = session.get(Aircraft, installed.tail_number)
    lines = []

    if plan.option == PlanOption.comat and plan.flight_number:
        adapter = get_cargo_adapter()
        try:
            confirmation = adapter.book(
                session,
                BookingRequest(
                    flight_number=plan.flight_number,
                    part_number=part.part_number,
                    serial=installed.serial,
                    weight_lb=part.weight_lb,
                ),
            )
            lines.append(
                f"iCargo booking confirmed: {confirmation.confirmation_number} "
                f"(AWB {confirmation.awb_number}) on {confirmation.flight_number}"
            )
        except CargoBookingError as e:
            lines.append(f"cargo booking failed: {e}")

    ticket = get_shipping_adapter().create_ticket(
        ShippingTicketRequest(
            plan_id=plan.id,
            option=plan.option.value,
            part_number=part.part_number,
            part_description=part.description,
            serial=installed.serial,
            source=plan.source,
            destination=aircraft.overnight_station,
            flight_number=plan.flight_number,
            is_dangerous_goods=part.is_dangerous_goods,
        )
    )
    lines.append(f"shipping ticket {ticket.ticket_number} / work order {ticket.work_order_number}")
    lines.extend(ticket.special_handling)

    session.add(
        PlanEvent(
            plan_id=plan.id,
            event_type=PlanEventType.shipped,
            created_at=datetime.now(),
            detail=" -- ".join(lines),
        )
    )


def approve_plan(session: Session, plan: Plan) -> Plan:
    if plan.pending_option is not None:
        # A flight change staged a new recommendation while this plan was
        # approved -- approving now adopts it.
        plan.option = plan.pending_option
        plan.source = plan.pending_source
        plan.flight_number = plan.pending_flight_number
        plan.cost = plan.pending_cost
        plan.risk_score = plan.pending_risk_score
        plan.reason = plan.pending_reason
        clear_pending(plan)

    plan.status = PlanStatus.approved
    session.add(plan)
    session.add(PlanEvent(plan_id=plan.id, event_type=PlanEventType.approved, created_at=datetime.now()))
    _fulfill_approved_plan(session, plan)
    session.commit()
    session.refresh(plan)
    return plan


def choose_alternative(
    session: Session,
    plan: Plan,
    installed: InstalledPart,
    option: PlanOption,
    source: str,
    flight_number: Optional[str],
    reason: OverrideReason,
    note: Optional[str],
) -> Plan:
    deadline = deadline_for(installed)
    candidates = build_candidates(session, installed)  # feasible only
    match = next(
        (
            c
            for c in candidates
            if c.option == option and c.source == source and c.flight_number == flight_number
        ),
        None,
    )
    if not match:
        raise NoSuchCandidate()

    label = OVERRIDE_REASON_LABELS[reason]
    note_clean = note.strip() if note else None
    reason_text = note_clean if (reason == OverrideReason.other and note_clean) else label

    scored = score_candidate(match, deadline)
    plan.option = match.option
    plan.source = match.source
    plan.flight_number = match.flight_number
    plan.cost = match.cost
    plan.risk_score = scored.risk_score
    plan.reason = f"Planner override: {reason_text}"
    plan.status = PlanStatus.approved
    clear_pending(plan)

    session.add(plan)
    via = f" via {match.flight_number}" if match.flight_number else ""
    session.add(
        PlanEvent(
            plan_id=plan.id,
            event_type=PlanEventType.overridden,
            created_at=datetime.now(),
            detail=f"chose {match.option.value} from {match.source}{via} instead -- {reason_text}",
        )
    )
    _fulfill_approved_plan(session, plan)
    session.commit()
    session.refresh(plan)
    return plan
