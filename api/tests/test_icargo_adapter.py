"""Covers the mock iCargo adapter: create_shipment -> book -> get_awb for
both plane_side (flight-checked) and to_cargo (no specific flight)
shipments, refusing an unbookable flight, fake AWBs always marked as
demo data, and the swap point (get_cargo_adapter / CARGO_ADAPTER).
"""

from datetime import datetime, time

import pytest

from app.adapters.icargo_adapter import (
    CargoBookingError,
    MockICargoAdapter,
    ShipmentRequest,
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


def _request(**overrides):
    defaults = dict(
        part_number="OXY-BTL-02", serial="SN-1", weight_lb=18,
        flight_number="EV2301", handoff_route="plane_side",
    )
    defaults.update(overrides)
    return ShipmentRequest(**defaults)


def test_plane_side_chain_books_the_named_flight(session, seeded_flight):
    adapter = MockICargoAdapter()
    shipment = adapter.create_shipment(session, _request())
    confirmation = adapter.book(session, shipment)
    awb = adapter.get_awb(session, shipment)

    assert confirmation.status == "confirmed"
    assert confirmation.flight_number == "EV2301"
    assert confirmation.booked_weight_lb == 18
    assert confirmation.confirmation_number.startswith("ICRG-")
    assert confirmation.source == "mock"
    assert awb.startswith("DEMO-AWB-")  # never mistakable for a real AWB


def test_to_cargo_chain_does_not_need_a_specific_flight(session):
    adapter = MockICargoAdapter()
    shipment = adapter.create_shipment(session, _request(flight_number=None, handoff_route="to_cargo"))
    confirmation = adapter.book(session, shipment)

    assert confirmation.status == "confirmed"
    assert confirmation.flight_number is None


def test_plane_side_without_a_flight_number_is_refused(session):
    adapter = MockICargoAdapter()
    shipment = adapter.create_shipment(session, _request(flight_number=None))
    with pytest.raises(CargoBookingError, match="needs a flight"):
        adapter.book(session, shipment)


def test_refuses_a_flight_without_enough_capacity(session, seeded_flight):
    adapter = MockICargoAdapter()
    shipment = adapter.create_shipment(session, _request(weight_lb=9999))
    with pytest.raises(CargoBookingError, match="capacity"):
        adapter.book(session, shipment)


def test_refuses_a_nonexistent_flight(session):
    adapter = MockICargoAdapter()
    shipment = adapter.create_shipment(session, _request(flight_number="EV9999"))
    with pytest.raises(CargoBookingError, match="no such flight"):
        adapter.book(session, shipment)


def test_refuses_a_cancelled_flight(session, seeded_flight):
    seeded_flight.status = FlightStatus.cancelled
    session.add(seeded_flight)
    session.commit()

    adapter = MockICargoAdapter()
    shipment = adapter.create_shipment(session, _request())
    with pytest.raises(CargoBookingError, match="cancelled"):
        adapter.book(session, shipment)


def test_get_cargo_adapter_defaults_to_mock(monkeypatch):
    monkeypatch.delenv("CARGO_ADAPTER", raising=False)
    assert isinstance(get_cargo_adapter(), MockICargoAdapter)


def test_get_cargo_adapter_is_the_documented_pilot_swap_point(monkeypatch):
    monkeypatch.setenv("CARGO_ADAPTER", "icargo")
    with pytest.raises(NotImplementedError, match="icargo"):
        get_cargo_adapter()
