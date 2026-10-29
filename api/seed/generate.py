"""Builds the synthetic regional-fleet dataset described in docs/spec.md.

Reads the static world (stations, aircraft, parts, vendors) from fleet.json
and layers on the time-relative, partly-randomized state: installed parts,
inventory snapshots, one day of flights, and vendor quotes. The hero scenario
and its two decoys are hardcoded, not randomized, so the demo never drifts.

Run with:  python -m seed.generate
"""

import json
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

from sqlmodel import SQLModel

from app.db import engine, init_db
from app.db import get_session
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

FLEET_PATH = Path(__file__).parent / "fleet.json"
SEED = 42
TODAY = date.today()

# Hero scenario: tail N501EV overnighting at CVG, oxygen bottle 2 days from
# expiry, serviceable spare at DFW, flown in on EV2301 tonight.
HERO_TAIL = "N501EV"
HERO_PART = "OXY-BTL-02"
HERO_DAYS_TO_EXPIRY = 2
HERO_CARRIER_TAIL = "N505EV"
HERO_FLIGHT_NUMBER = "EV2301"

# Decoy 1: a spare of the same part at ORD, but unserviceable.
DECOY_UNSERVICEABLE_STATION = "ORD"

# Decoy 2: a cheaper vendor quote that arrives after the deadline.
DECOY_VENDOR = "SkyParts Direct"
DECOY_VENDOR_PRICE = 610.0
DECOY_VENDOR_LEAD_HRS = 60.0  # deadline is 48 hrs out; this misses it

# A few more parts forced into the 7-day expiry window, on other tails, so
# the queue has 5-6 entries total (hero + these) instead of just one.
NEAR_EXPIRY_OVERRIDES = [
    ("N503EV", "ELT-BATT-406", 1),
    ("N508EV", "FIRE-EXT-HALON", 4),
    ("N512EV", "LIFE-VEST-ADULT", 6),
    ("N516EV", "EMK-DOC", 7),
]

CARGO_CAPACITY_LB = {"E175": 2500.0, "CRJ900": 2200.0}


def load_fleet() -> dict:
    return json.loads(FLEET_PATH.read_text())


def seed_stations(session, fleet: dict) -> None:
    for s in fleet["stations"]:
        session.add(Station(**s))


def seed_aircraft(session, fleet: dict) -> None:
    for a in fleet["aircraft"]:
        session.add(Aircraft(**a))


def seed_parts(session, fleet: dict) -> dict:
    parts_by_number = {}
    for p in fleet["parts"]:
        part = Part(
            part_number=p["part_number"],
            description=p["description"],
            shelf_life_days=p["shelf_life_days"],
            is_rotable=p["is_rotable"],
            unit_cost=p["unit_cost"],
            weight_lb=p["weight_lb"],
            is_dangerous_goods=p.get("is_dangerous_goods", False),
            dg_class=p.get("dg_class"),
            is_oversize=p.get("is_oversize", False),
        )
        session.add(part)
        parts_by_number[p["part_number"]] = p
    return parts_by_number


def seed_installed_parts(session, fleet: dict, parts_by_number: dict, rng: random.Random) -> None:
    override_by_tail = {tail: (part_no, days) for tail, part_no, days in NEAR_EXPIRY_OVERRIDES}
    part_numbers = list(parts_by_number.keys())

    for a in fleet["aircraft"]:
        tail = a["tail_number"]
        assigned: set[str] = set()

        if tail == HERO_TAIL:
            _add_installed_part(session, tail, HERO_PART, parts_by_number, HERO_DAYS_TO_EXPIRY)
            assigned.add(HERO_PART)
        elif tail in override_by_tail:
            part_no, days = override_by_tail[tail]
            _add_installed_part(session, tail, part_no, parts_by_number, days)
            assigned.add(part_no)

        # Fill remaining slots (every tail carries 2 tracked parts) with
        # expiry dates well outside the 7-day window.
        while len(assigned) < 2:
            candidate = rng.choice(part_numbers)
            if candidate in assigned:
                continue
            days_out = rng.randint(60, 500)
            _add_installed_part(session, tail, candidate, parts_by_number, days_out)
            assigned.add(candidate)


def _add_installed_part(session, tail: str, part_no: str, parts_by_number: dict, days_to_expiry: int) -> None:
    part = parts_by_number[part_no]
    expires_on = TODAY + timedelta(days=days_to_expiry)
    installed_on = expires_on - timedelta(days=min(part["shelf_life_days"], 3650))
    session.add(
        InstalledPart(
            serial=f"SN-{tail}-{part_no}",
            part_number=part_no,
            tail_number=tail,
            position=part["position"],
            installed_on=installed_on,
            expires_on=expires_on,
            hours_remaining=None,
        )
    )


def seed_inventory(session, fleet: dict, parts_by_number: dict, rng: random.Random) -> None:
    # Hero spare: serviceable, at DFW.
    session.add(
        InventoryItem(
            serial=f"INV-DFW-{HERO_PART}-1",
            part_number=HERO_PART,
            station="DFW",
            condition=InventoryCondition.serviceable,
            expires_on=TODAY + timedelta(days=400),
            last_counted_on=TODAY - timedelta(days=1),
        )
    )
    # Decoy: an ORD spare of the same part, but unserviceable.
    session.add(
        InventoryItem(
            serial=f"INV-{DECOY_UNSERVICEABLE_STATION}-{HERO_PART}-1",
            part_number=HERO_PART,
            station=DECOY_UNSERVICEABLE_STATION,
            condition=InventoryCondition.unserviceable,
            expires_on=TODAY + timedelta(days=400),
            last_counted_on=TODAY - timedelta(days=2),
        )
    )

    part_numbers = list(parts_by_number.keys())
    for s in fleet["stations"]:
        station = s["code"]
        for part_no in rng.sample(part_numbers, k=4):
            session.add(
                InventoryItem(
                    serial=f"INV-{station}-{part_no}-fill",
                    part_number=part_no,
                    station=station,
                    condition=InventoryCondition.serviceable,
                    expires_on=TODAY + timedelta(days=rng.randint(90, 600)),
                    last_counted_on=TODAY - timedelta(days=rng.randint(0, 10)),
                )
            )


def seed_flights(session, fleet: dict, rng: random.Random) -> None:
    next_flight_num = 2302
    for a in fleet["aircraft"]:
        tail = a["tail_number"]
        origin, dest = a["current_station"], a["overnight_station"]
        if origin == dest:
            continue  # already parked there tonight, no flight needed

        if tail == HERO_CARRIER_TAIL:
            flight_number = HERO_FLIGHT_NUMBER
            dep_time = time(18, 40)
            arr_time = time(20, 25)
        else:
            flight_number = f"EV{next_flight_num}"
            next_flight_num += 1
            dep_hour = rng.randint(6, 20)
            dep_time = time(dep_hour, rng.choice([0, 15, 30, 45]))
            arr_time = time(min(dep_hour + 1, 23), rng.choice([0, 15, 30, 45]))

        session.add(
            Flight(
                flight_number=flight_number,
                tail_number=tail,
                origin=origin,
                dest=dest,
                sched_dep=datetime.combine(TODAY, dep_time),
                sched_arr=datetime.combine(TODAY, arr_time),
                status=FlightStatus.scheduled,
                cargo_capacity_lb=CARGO_CAPACITY_LB[a["type"]],
                # Every seeded flight accepts DG for now (all domestic, same
                # fleet type); a deliberate "DG part, not every flight is
                # DG-approved" decoy is a later seed-data step.
                accepts_dg=True,
            )
        )


def seed_vendor_quotes(session, fleet: dict, rng: random.Random) -> None:
    # Decoy: cheap, but arrives after the hero part's deadline.
    session.add(
        VendorQuote(
            vendor=DECOY_VENDOR,
            part_number=HERO_PART,
            price=DECOY_VENDOR_PRICE,
            lead_time_hrs=DECOY_VENDOR_LEAD_HRS,
            ship_to_station="CVG",
            certs="FAA 8130-3",
        )
    )
    # A real (pricier, faster) buy option for the same part, so "buy" is a
    # genuine candidate the planner can still rank behind COMAT.
    session.add(
        VendorQuote(
            vendor="AeroSource",
            part_number=HERO_PART,
            price=780.0,
            lead_time_hrs=20.0,
            ship_to_station="CVG",
            certs="FAA 8130-3",
        )
    )

    part_numbers = [p["part_number"] for p in fleet["parts"] if p["part_number"] != HERO_PART]
    for part_no in rng.sample(part_numbers, k=10):
        vendor = rng.choice(fleet["vendors"])
        session.add(
            VendorQuote(
                vendor=vendor,
                part_number=part_no,
                price=round(rng.uniform(100, 20000), 2),
                lead_time_hrs=round(rng.uniform(4, 96), 1),
                ship_to_station=rng.choice([s["code"] for s in fleet["stations"]]),
                certs="FAA 8130-3",
            )
        )


def main() -> None:
    fleet = load_fleet()
    rng = random.Random(SEED)

    # Reset so re-running the seed always produces the same demo state.
    SQLModel.metadata.drop_all(engine)
    init_db()

    with get_session() as session:
        seed_stations(session, fleet)
        seed_aircraft(session, fleet)
        parts_by_number = seed_parts(session, fleet)
        session.flush()

        seed_installed_parts(session, fleet, parts_by_number, rng)
        seed_inventory(session, fleet, parts_by_number, rng)
        seed_flights(session, fleet, rng)
        seed_vendor_quotes(session, fleet, rng)

        session.commit()

    print(f"Seeded comat.db: {len(fleet['stations'])} stations, "
          f"{len(fleet['aircraft'])} aircraft, {len(fleet['parts'])} parts.")


if __name__ == "__main__":
    main()
