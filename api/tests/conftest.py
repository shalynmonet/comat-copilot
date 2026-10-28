"""Shared fixtures: an isolated in-memory DB seeded with the hero scenario
(N501EV's oxygen bottle, the DFW spare, the EV2301 flight) and both decoys
(the unserviceable ORD spare, the too-slow vendor quote).
"""

from datetime import date, datetime, time, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.models import (
    Aircraft,
    Flight,
    FlightStatus,
    InstalledPart,
    InventoryCondition,
    InventoryItem,
    Part,
    Station,
    VendorQuote,
)

TODAY = date.today()
NOW = datetime.combine(TODAY, time(8, 0))  # fixed so tests don't depend on wall-clock time
HERO_EXPIRES_ON = TODAY + timedelta(days=2)
DEADLINE = datetime.combine(HERO_EXPIRES_ON, time.min)


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture()
def hero_part(session):
    session.add_all(
        [
            Station(code="DFW", name="Dallas-Fort Worth", lat=32.8998, lon=-97.0403, has_maintenance=True, stores_capacity=500),
            Station(code="CVG", name="Cincinnati/N. Kentucky", lat=39.0488, lon=-84.6678, has_maintenance=False, stores_capacity=80),
            Station(code="ORD", name="Chicago O'Hare", lat=41.9742, lon=-87.9073, has_maintenance=True, stores_capacity=300),
            Aircraft(tail_number="N501EV", type="E175", current_station="CVG", overnight_station="CVG"),
            Part(part_number="OXY-BTL-02", description="Crew Oxygen Bottle, 2L", shelf_life_days=730, is_rotable=False, unit_cost=850, weight_lb=18),
        ]
    )
    installed = InstalledPart(
        serial="SN-N501EV-OXY-BTL-02",
        part_number="OXY-BTL-02",
        tail_number="N501EV",
        position="OXY-CREW-1",
        installed_on=HERO_EXPIRES_ON - timedelta(days=730),
        expires_on=HERO_EXPIRES_ON,
    )
    session.add(installed)

    # Decoy 1: unserviceable spare at ORD.
    session.add(
        InventoryItem(
            serial="INV-ORD-OXY-BTL-02-1",
            part_number="OXY-BTL-02",
            station="ORD",
            condition=InventoryCondition.unserviceable,
            expires_on=TODAY + timedelta(days=400),
            last_counted_on=TODAY,
        )
    )
    # The real spare: serviceable at DFW.
    session.add(
        InventoryItem(
            serial="INV-DFW-OXY-BTL-02-1",
            part_number="OXY-BTL-02",
            station="DFW",
            condition=InventoryCondition.serviceable,
            expires_on=TODAY + timedelta(days=400),
            last_counted_on=TODAY,
        )
    )
    # The flight that carries it in tonight.
    session.add(
        Flight(
            flight_number="EV2301",
            tail_number="N505EV",
            origin="DFW",
            dest="CVG",
            sched_dep=datetime.combine(TODAY, time(18, 40)),
            sched_arr=datetime.combine(TODAY, time(20, 25)),
            status=FlightStatus.scheduled,
            cargo_capacity_lb=2500.0,
        )
    )
    # Decoy 2: cheaper vendor quote that arrives after the deadline.
    session.add(
        VendorQuote(
            vendor="SkyParts Direct",
            part_number="OXY-BTL-02",
            price=610.0,
            lead_time_hrs=60.0,
            ship_to_station="CVG",
            certs="FAA 8130-3",
        )
    )
    # A real, faster-but-pricier buy option.
    session.add(
        VendorQuote(
            vendor="AeroSource",
            part_number="OXY-BTL-02",
            price=780.0,
            lead_time_hrs=20.0,
            ship_to_station="CVG",
            certs="FAA 8130-3",
        )
    )
    session.commit()
    return installed
