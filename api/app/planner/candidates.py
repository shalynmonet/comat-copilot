"""Finds every way to cover an expiring installed part: COMAT (ride an
existing flight), transfer (ground courier from another station), or buy
(vendor). A candidate that can't arrive before the part's deadline, or that
would use a non-serviceable spare, is still produced -- just flagged
`disqualified` with a human-readable reason -- so the UI can show the full
menu of options rather than silently hiding the rejected ones. Only
`build_candidates(..., include_disqualified=True)` (the UI-facing route)
asks for those; the planner's own scoring/selection code keeps getting the
feasible-only list it always has.
"""

import math
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional

from sqlmodel import Session, select

from app.models import (
    Aircraft,
    Flight,
    FlightStatus,
    InstalledPart,
    InventoryCondition,
    InventoryItem,
    Part,
    PlanOption,
    Station,
    VendorQuote,
)

COMAT_HANDLING_FEE = 25.0

TRANSFER_RATE_PER_MILE = 3.0
TRANSFER_DISPATCH_FEE = 50.0
TRANSFER_GROUND_SPEED_MPH = 50.0
TRANSFER_HANDLING_HOURS = 1.0

BUY_EXPEDITE_FEE = 150.0

EARTH_RADIUS_MILES = 3958.8


@dataclass
class Candidate:
    option: PlanOption
    source: str
    flight_number: Optional[str]
    cost: float
    eta: datetime
    detail: str
    disqualified: bool = False
    disqualified_reason: Optional[str] = None
    is_dangerous_goods: bool = False


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def _spares(session: Session, part_number: str, exclude_station: str) -> list[InventoryItem]:
    rows = session.exec(
        select(InventoryItem).where(
            InventoryItem.part_number == part_number,
            InventoryItem.station != exclude_station,
        )
    ).all()
    return list(rows)


def _comat_candidates(
    session: Session, part: Part, destination: str, now: datetime, deadline: datetime
) -> list[Candidate]:
    candidates = []
    for spare in _spares(session, part.part_number, destination):
        flights = session.exec(
            select(Flight).where(
                Flight.origin == spare.station,
                Flight.dest == destination,
                Flight.status.in_([FlightStatus.scheduled, FlightStatus.delayed]),
                Flight.sched_dep >= now,
            )
        ).all()
        for flight in flights:
            reason = None
            if spare.condition != InventoryCondition.serviceable:
                reason = f"the {spare.station} spare is {spare.condition.value}"
            elif flight.cargo_capacity_lb < part.weight_lb:
                reason = f"flight {flight.flight_number} doesn't have the cargo capacity for this part"
            elif flight.sched_arr > deadline:
                reason = f"flight {flight.flight_number} arrives after the deadline"

            candidates.append(
                Candidate(
                    option=PlanOption.comat,
                    source=spare.station,
                    flight_number=flight.flight_number,
                    cost=COMAT_HANDLING_FEE,
                    eta=flight.sched_arr,
                    detail=f"ride flight {flight.flight_number} from {spare.station}, arrives {flight.sched_arr:%H:%M}",
                    disqualified=reason is not None,
                    disqualified_reason=reason,
                    is_dangerous_goods=part.is_dangerous_goods,
                )
            )
    return candidates


def _transfer_candidates(
    session: Session, part: Part, destination: str, now: datetime, deadline: datetime
) -> list[Candidate]:
    dest_station = session.get(Station, destination)
    candidates = []
    for spare in _spares(session, part.part_number, destination):
        source_station = session.get(Station, spare.station)
        distance = _haversine_miles(
            source_station.lat, source_station.lon, dest_station.lat, dest_station.lon
        )
        transit_hours = distance / TRANSFER_GROUND_SPEED_MPH + TRANSFER_HANDLING_HOURS
        eta = now + timedelta(hours=transit_hours)
        cost = distance * TRANSFER_RATE_PER_MILE + TRANSFER_DISPATCH_FEE

        reason = None
        if spare.condition != InventoryCondition.serviceable:
            reason = f"the {spare.station} spare is {spare.condition.value}"
        elif eta > deadline:
            reason = "ground transfer would arrive after the deadline"

        candidates.append(
            Candidate(
                option=PlanOption.transfer,
                source=spare.station,
                flight_number=None,
                cost=round(cost, 2),
                eta=eta,
                detail=f"ground transfer from {spare.station}, {distance:.0f} mi, arrives {eta:%H:%M}",
                disqualified=reason is not None,
                disqualified_reason=reason,
                is_dangerous_goods=part.is_dangerous_goods,
            )
        )
    return candidates


def _buy_candidates(
    session: Session, part: Part, destination: str, now: datetime, deadline: datetime
) -> list[Candidate]:
    quotes = session.exec(
        select(VendorQuote).where(
            VendorQuote.part_number == part.part_number,
            VendorQuote.ship_to_station == destination,
        )
    ).all()
    candidates = []
    for quote in quotes:
        eta = now + timedelta(hours=quote.lead_time_hrs)
        reason = "vendor lead time means it arrives after the deadline" if eta > deadline else None
        candidates.append(
            Candidate(
                option=PlanOption.buy,
                source=quote.vendor,
                flight_number=None,
                cost=round(quote.price + BUY_EXPEDITE_FEE, 2),
                eta=eta,
                detail=f"buy from {quote.vendor}, lead time {quote.lead_time_hrs:.0f}h",
                disqualified=reason is not None,
                disqualified_reason=reason,
                is_dangerous_goods=part.is_dangerous_goods,
            )
        )
    return candidates


def deadline_for(installed_part: InstalledPart) -> datetime:
    return datetime.combine(installed_part.expires_on, time.min)


def build_candidates(
    session: Session,
    installed_part: InstalledPart,
    now: Optional[datetime] = None,
    include_disqualified: bool = False,
) -> list[Candidate]:
    now = now or datetime.now()
    part = session.get(Part, installed_part.part_number)
    aircraft = session.get(Aircraft, installed_part.tail_number)
    destination = aircraft.overnight_station
    deadline = deadline_for(installed_part)

    candidates = (
        _comat_candidates(session, part, destination, now, deadline)
        + _transfer_candidates(session, part, destination, now, deadline)
        + _buy_candidates(session, part, destination, now, deadline)
    )
    if include_disqualified:
        return candidates
    return [c for c in candidates if not c.disqualified]
