"""Finds bookable flight options between two stations: direct legs, and
one-stop connections through hub stations (has_maintenance=True, same
as DFW/ORD in the seed data). A leg is bookable only outside its booking
cutoff (60 min domestic, 90 international, from api/config), has cargo
capacity for the part, and -- if the part is dangerous goods -- only
flies on a flight whose accepts_dg is true.

This module only returns genuinely bookable options; it doesn't do the
"disqualified but shown" formatting candidates.py does for the UI, since
at this layer there's no plan yet to attach a reason to. Call it from
candidates.py (or wherever a plan is being built) to get the legs, then
decide what to do with the ones that didn't make it.

An AOG-desk override bypasses the cutoff. This module just signals that
a leg only qualified because of the override (`used_override` on the
leg) -- logging it as a plan_event happens wherever a Plan actually
exists to attach the event to.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from app.config import load_private_codes
from app.models import Flight, FlightStatus, Part, Station


@dataclass
class BookableLeg:
    flight: Flight
    used_override: bool = False


@dataclass
class FlightOption:
    legs: list[BookableLeg]  # 1 leg (direct) or 2 legs (connection)
    arrival: datetime  # arrival of the final leg
    used_override: bool  # true if any leg only qualified via the AOG desk

    @property
    def is_connection(self) -> bool:
        return len(self.legs) > 1

    @property
    def hub(self) -> Optional[str]:
        return self.legs[0].flight.dest if self.is_connection else None


def leg_bookability(
    flight: Flight, now: datetime, aog_desk_override: bool = False
) -> tuple[bool, bool, Optional[str]]:
    """Returns (bookable, used_override, reason_if_not_bookable)."""
    if flight.status not in (FlightStatus.scheduled, FlightStatus.delayed):
        return False, False, f"flight {flight.flight_number} is {flight.status.value}"

    codes = load_private_codes()
    cutoff_minutes = (
        codes.booking_cutoff_minutes_international
        if flight.is_international
        else codes.booking_cutoff_minutes_domestic
    )
    minutes_to_departure = (flight.sched_dep - now).total_seconds() / 60

    if minutes_to_departure <= cutoff_minutes:
        if aog_desk_override:
            return True, True, None
        kind = "international" if flight.is_international else "domestic"
        return (
            False,
            False,
            f"flight {flight.flight_number} departs in {minutes_to_departure:.0f} min, "
            f"inside the {cutoff_minutes}-min {kind} booking cutoff",
        )
    return True, False, None


def _leg_usable(flight: Flight, part: Part, now: datetime, aog_desk_override: bool) -> Optional[BookableLeg]:
    if part.is_dangerous_goods and not flight.accepts_dg:
        return None
    if flight.cargo_capacity_lb < part.weight_lb:
        return None
    bookable, used_override, _reason = leg_bookability(flight, now, aog_desk_override)
    if not bookable:
        return None
    return BookableLeg(flight=flight, used_override=used_override)


def _flights_from(session: Session, origin: str, now: datetime) -> list[Flight]:
    return list(
        session.exec(
            select(Flight).where(
                Flight.origin == origin,
                Flight.status.in_([FlightStatus.scheduled, FlightStatus.delayed]),
                Flight.sched_dep >= now,
            )
        ).all()
    )


def search_flight_options(
    session: Session,
    origin: str,
    destination: str,
    part: Part,
    now: datetime,
    deadline: datetime,
    aog_desk_override: bool = False,
) -> list[FlightOption]:
    options: list[FlightOption] = []

    # Direct legs.
    for flight in _flights_from(session, origin, now):
        if flight.dest != destination:
            continue
        leg = _leg_usable(flight, part, now, aog_desk_override)
        if leg and leg.flight.sched_arr <= deadline:
            options.append(FlightOption(legs=[leg], arrival=leg.flight.sched_arr, used_override=leg.used_override))

    # One-stop connections through hub stations.
    hub_codes = {s.code for s in session.exec(select(Station).where(Station.has_maintenance == True)).all()}  # noqa: E712
    for hub in hub_codes:
        if hub in (origin, destination):
            continue
        first_legs = [f for f in _flights_from(session, origin, now) if f.dest == hub]
        if not first_legs:
            continue
        second_flights = session.exec(
            select(Flight).where(
                Flight.origin == hub,
                Flight.dest == destination,
                Flight.status.in_([FlightStatus.scheduled, FlightStatus.delayed]),
            )
        ).all()
        if not second_flights:
            continue

        for first in first_legs:
            leg1 = _leg_usable(first, part, now, aog_desk_override)
            if not leg1:
                continue
            for second in second_flights:
                if second.sched_dep < leg1.flight.sched_arr:
                    continue  # can't catch a connection that leaves before this one lands
                leg2 = _leg_usable(second, part, now, aog_desk_override)
                if not leg2 or leg2.flight.sched_arr > deadline:
                    continue
                options.append(
                    FlightOption(
                        legs=[leg1, leg2],
                        arrival=leg2.flight.sched_arr,
                        used_override=leg1.used_override or leg2.used_override,
                    )
                )

    return options
