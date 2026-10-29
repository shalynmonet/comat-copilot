"""Covers the mock iCargo adapter: it should confirm a booking when the
flight exists and has room, refuse one that doesn't, and the swap point
(get_cargo_adapter / CARGO_ADAPTER) should behave as documented.
"""

from datetime import datetime, time

import pytest

from app.adapters.icargo_adapter import (
    BookingRequest,
    CargoBookingError,
    MockICargoAdapter,
    get_cargo_adapter,
)
from app.models import Flight, FlightStatus, Station


@pytest.fixture()
def seeded_flight(session):
    session.add_all(
        [
            Station(code="DFW", name="Dallas-Fort Worth", lat=32.8998, lon=-97.0403),
            Station(code="CVG", name="Cincinnati/N. Kentucky", lat=39.0488, lon=-84.6678),
        ]
    )
    flight = Flight(
        flight_number="EV2301",
        tail_number="N505EV",
        origin="DFW",
        dest="CVG",
        sched_dep=datetime.combine(datetime.now().date(), time(18, 40)),
        sched_arr=datetime.combine(datetime.now().date(), time(20, 25)),
        status=FlightStatus.scheduled,
        cargo_capacity_lb=2500.0,
    )
    session.add(flight)
    session.commit()
    return flight


def test_books_a_flight_with_room(session, seeded_flight):
    adapter = MockICargoAdapter()
    confirmation = adapter.book(
        session, BookingRequest(flight_number="EV2301", part_number="OXY-BTL-02", serial="SN-1", weight_lb=18)
    )

    assert confirmation.status == "confirmed"
    assert confirmation.flight_number == "EV2301"
    assert confirmation.booked_weight_lb == 18
    assert confirmation.confirmation_number.startswith("ICRG-")
    assert confirmation.awb_number.startswith("AWB-")
    assert confirmation.source == "mock"


def test_refuses_a_flight_without_enough_capacity(session, seeded_flight):
    adapter = MockICargoAdapter()
    with pytest.raises(CargoBookingError, match="capacity"):
        adapter.book(
            session,
            BookingRequest(flight_number="EV2301", part_number="BRAKE-ASSY", serial="SN-2", weight_lb=9999),
        )


def test_refuses_a_nonexistent_flight(session):
    adapter = MockICargoAdapter()
    with pytest.raises(CargoBookingError, match="no such flight"):
        adapter.book(
            session,
            BookingRequest(flight_number="EV9999", part_number="OXY-BTL-02", serial="SN-3", weight_lb=18),
        )


def test_refuses_a_cancelled_flight(session, seeded_flight):
    seeded_flight.status = FlightStatus.cancelled
    session.add(seeded_flight)
    session.commit()

    adapter = MockICargoAdapter()
    with pytest.raises(CargoBookingError, match="cancelled"):
        adapter.book(
            session,
            BookingRequest(flight_number="EV2301", part_number="OXY-BTL-02", serial="SN-4", weight_lb=18),
        )


def test_get_cargo_adapter_defaults_to_mock(monkeypatch):
    monkeypatch.delenv("CARGO_ADAPTER", raising=False)
    assert isinstance(get_cargo_adapter(), MockICargoAdapter)


def test_get_cargo_adapter_is_the_documented_pilot_swap_point(monkeypatch):
    monkeypatch.setenv("CARGO_ADAPTER", "icargo")
    with pytest.raises(NotImplementedError, match="icargo"):
        get_cargo_adapter()
