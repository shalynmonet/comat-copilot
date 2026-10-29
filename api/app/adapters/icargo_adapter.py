"""Cargo booking adapter.

A COMAT or to_cargo shipment rides space arranged through iCargo -- in a
pilot, that means three real API calls: create the shipment, book the
space, and issue the air waybill. Today there's no iCargo account to
call, so `MockICargoAdapter` answers those same three calls from our own
seeded flight/capacity data. `ShipmentRequest` in, a `ShipmentHandle`
and then a `BookingConfirmation`/AWB out, either way: a pilot sets
`CARGO_ADAPTER=icargo`, a real client gets registered in
`get_cargo_adapter()`, and nothing that calls this module changes.

Fake AWB numbers are always prefixed DEMO-AWB- so they're never
mistaken for a real one.
"""

from __future__ import annotations

import os
import random
import string
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol

from sqlmodel import Session, select

from app.models import Flight, FlightStatus


@dataclass
class ShipmentRequest:
    part_number: str
    serial: str
    weight_lb: float
    flight_number: Optional[str]
    handoff_route: str  # "plane_side" | "to_cargo"


@dataclass
class ShipmentHandle:
    shipment_id: str
    request: ShipmentRequest


@dataclass
class BookingConfirmation:
    confirmation_number: str
    flight_number: Optional[str]
    booked_weight_lb: float
    status: str  # "confirmed"
    booked_at: datetime
    source: str  # "mock" | "icargo"
    detail: str


class CargoBookingError(Exception):
    """The adapter couldn't confirm the booking (no such flight, no capacity, ...)."""


class CargoAdapter(Protocol):
    def create_shipment(self, session: Session, request: ShipmentRequest) -> ShipmentHandle: ...
    def book(self, session: Session, shipment: ShipmentHandle) -> BookingConfirmation: ...
    def get_awb(self, session: Session, shipment: ShipmentHandle) -> str: ...


def _reference(prefix: str, length: int) -> str:
    chars = string.ascii_uppercase + string.digits
    return f"{prefix}-{''.join(random.choices(chars, k=length))}"


class MockICargoAdapter:
    """Stands in for iCargo. plane_side shipments are checked against the
    named flight's own status and cargo capacity -- the same two facts a
    real booking call would need; to_cargo shipments go through the
    Cargo division rather than a specific flight, so there's no single
    flight to validate against."""

    source = "mock"

    def create_shipment(self, session: Session, request: ShipmentRequest) -> ShipmentHandle:
        return ShipmentHandle(shipment_id=_reference("SHIP", 8), request=request)

    def book(self, session: Session, shipment: ShipmentHandle) -> BookingConfirmation:
        request = shipment.request

        if request.handoff_route == "plane_side":
            if not request.flight_number:
                raise CargoBookingError("iCargo: a plane-side shipment needs a flight to book")
            flight = session.exec(select(Flight).where(Flight.flight_number == request.flight_number)).first()
            if not flight:
                raise CargoBookingError(f"iCargo: no such flight {request.flight_number}")
            if flight.status == FlightStatus.cancelled:
                raise CargoBookingError(f"iCargo: flight {request.flight_number} is cancelled")
            if flight.cargo_capacity_lb < request.weight_lb:
                raise CargoBookingError(
                    f"iCargo: flight {request.flight_number} doesn't have "
                    f"{request.weight_lb:.0f} lb of free cargo capacity"
                )

        via = f" on {request.flight_number}" if request.flight_number else " via Cargo"
        return BookingConfirmation(
            confirmation_number=_reference("ICRG", 6),
            flight_number=request.flight_number,
            booked_weight_lb=request.weight_lb,
            status="confirmed",
            booked_at=datetime.now(),
            source=self.source,
            detail=(
                f"{request.handoff_route} space booked{via} for part {request.part_number} "
                f"(serial {request.serial}), {request.weight_lb:.0f} lb"
            ),
        )

    def get_awb(self, session: Session, shipment: ShipmentHandle) -> str:
        return _reference("DEMO-AWB", 9)


def get_cargo_adapter() -> CargoAdapter:
    """The pilot swap point: set CARGO_ADAPTER=icargo and register a class
    here with the same create_shipment()/book()/get_awb() signatures,
    pointed at real credentials. Nothing that calls get_cargo_adapter()
    has to change."""
    backend = os.environ.get("CARGO_ADAPTER", "mock")
    if backend == "mock":
        return MockICargoAdapter()
    raise NotImplementedError(
        f"CARGO_ADAPTER={backend!r} isn't wired up yet -- implement a CargoAdapter "
        "for it and register it in get_cargo_adapter()."
    )
