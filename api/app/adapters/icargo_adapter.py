"""Cargo booking adapter.

A COMAT option rides space on a real revenue flight -- in a pilot, holding
that space means a call to iCargo's booking API. Today there's no iCargo
account to call, so `MockICargoAdapter` answers that same call from our own
seeded flight/capacity data instead. `BookingRequest` in, `BookingConfirmation`
out, either way: a pilot sets `CARGO_ADAPTER=icargo`, a real client gets
registered in `get_cargo_adapter()`, and nothing that calls this module
changes.
"""

from __future__ import annotations

import os
import random
import string
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlmodel import Session, select

from app.models import Flight, FlightStatus


@dataclass
class BookingRequest:
    flight_number: str
    part_number: str
    serial: str
    weight_lb: float


@dataclass
class BookingConfirmation:
    confirmation_number: str
    awb_number: str
    flight_number: str
    booked_weight_lb: float
    status: str  # "confirmed"
    booked_at: datetime
    source: str  # "mock" | "icargo"
    detail: str


class CargoBookingError(Exception):
    """The adapter couldn't confirm the booking (no such flight, no capacity, ...)."""


class CargoAdapter(Protocol):
    def book(self, session: Session, request: BookingRequest) -> BookingConfirmation: ...


def _reference(prefix: str, length: int) -> str:
    chars = string.ascii_uppercase + string.digits
    return f"{prefix}-{''.join(random.choices(chars, k=length))}"


class MockICargoAdapter:
    """Stands in for iCargo's booking API. Looks up the flight and its cargo
    capacity from our own seed data -- the same two facts a real booking
    call needs -- and returns a confirmation shaped like a real one would be
    (a confirmation number plus an air waybill number)."""

    source = "mock"

    def book(self, session: Session, request: BookingRequest) -> BookingConfirmation:
        flight = session.exec(
            select(Flight).where(Flight.flight_number == request.flight_number)
        ).first()
        if not flight:
            raise CargoBookingError(f"iCargo: no such flight {request.flight_number}")
        if flight.status == FlightStatus.cancelled:
            raise CargoBookingError(f"iCargo: flight {request.flight_number} is cancelled")
        if flight.cargo_capacity_lb < request.weight_lb:
            raise CargoBookingError(
                f"iCargo: flight {request.flight_number} doesn't have "
                f"{request.weight_lb:.0f} lb of free cargo capacity"
            )

        return BookingConfirmation(
            confirmation_number=_reference("ICRG", 6),
            awb_number=_reference("AWB", 9),
            flight_number=request.flight_number,
            booked_weight_lb=request.weight_lb,
            status="confirmed",
            booked_at=datetime.now(),
            source=self.source,
            detail=(
                f"COMAT space held on {request.flight_number} for part {request.part_number} "
                f"(serial {request.serial}), {request.weight_lb:.0f} lb"
            ),
        )


def get_cargo_adapter() -> CargoAdapter:
    """The pilot swap point: set CARGO_ADAPTER=icargo and register a class
    here with the same book() signature, pointed at real credentials.
    Nothing that calls get_cargo_adapter() has to change."""
    backend = os.environ.get("CARGO_ADAPTER", "mock")
    if backend == "mock":
        return MockICargoAdapter()
    raise NotImplementedError(
        f"CARGO_ADAPTER={backend!r} isn't wired up yet -- implement a CargoAdapter "
        "for it and register it in get_cargo_adapter()."
    )
