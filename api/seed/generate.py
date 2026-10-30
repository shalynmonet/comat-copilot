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
    Priority,
    RaisedBy,
    RemovalHistory,
    RemovalReason,
    ShippingRequest,
    ShippingRequestStatus,
    Station,
    VendorQuote,
)
from app.adapters.m3_adapter import get_m3_adapter
from app.planner.intake import raise_copilot_requests
from seed.tag_images import main as generate_tag_images

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

# DG decoy: a second, serviceable OXY-BTL-02 spare at ORD -- reachable only
# by DG_DECOY_TAIL's ORD -> CVG flight, which is the one flight in the
# fleet deliberately not DG-approved. Shows up as a feasible-looking
# candidate that's disqualified specifically for the DG restriction,
# alongside the already-serviceable DFW spare that *does* ride DG.
DG_DECOY_TAIL = "N516EV"

# That same ORD spare also looks low-confidence: never individually
# photo-verified, moved around a lot recently, at a station with a real
# discrepancy history -- below the verification threshold without
# disturbing the hero's own DFW-sourced plan. Paired with a seeded tag
# photo that *doesn't* match this record (see app/adapters/verify_tag.py)
# so the mismatch/phantom-flag flow is directly demoable.
LOW_CONFIDENCE_STATION = "ORD"
LOW_CONFIDENCE_DISCREPANCY_RATE = 0.35
LOW_CONFIDENCE_MOVE_COUNT_30D = 5

# Connection scenario: a second expiring part on the hero's own tail,
# whose only spare is at TUL -- no direct TUL -> CVG flight exists, so
# the planner has to find it via the TUL -> DFW -> CVG connection
# (CONNECTION_HUB_TAIL's leg into DFW, then the hero's own EV2301 onward).
CONNECTION_PART = "HYD-PUMP-B"
CONNECTION_STATION = "TUL"
CONNECTION_DAYS_TO_EXPIRY = 3
CONNECTION_HUB_TAIL = "N511EV"
CONNECTION_FLIGHT_NUMBER = "EV2250"

# Oversize scenario: a critical (short-fused) part that's also oversize,
# so it must be routed critical_cargo rather than critical_planeside.
OVERSIZE_PART = "TIRE-MAIN"
OVERSIZE_STATION = "OKC"
OVERSIZE_DAYS_TO_EXPIRY = 1
OVERSIZE_TAIL = "N513EV"

# A real AOG: already past its expiry, raised directly by maintenance
# control (not Copilot's scan) -- the kind of firefighting Copilot's
# early warning is meant to prevent more of.
AOG_TAIL = "N502EV"
AOG_PART = "APU-BATT"
AOG_DAYS_TO_EXPIRY = -1

# Pick-and-issue demo: an open part request waiting in the PickSlip,
# where the shelf tag at the expected bin doesn't match M3's record --
# the stock clerk discovers the phantom part at pick time instead of a
# plan-approval verify_task.
PICK_PART = "STARTER-GEN"
PICK_STATION = "AUS"
PICK_TAIL = "N509EV"
PICK_MECHANIC = "Mike (Line Maint)"
PICK_LOCATION = "BIN-AUS-07"
PICK_SERIAL = "INV-AUS-STARTER-GEN-1"

# Expiring-lots demo (M3's Expiring Lot Report): one lot another station
# genuinely needs before it expires (move), one with no demand anywhere
# (replace -- with no other spare at its station, so Copilot also raises
# a replacement request).
EXPIRING_MOVE_PART = "FAK-STD"
EXPIRING_MOVE_LOT_STATION = "ORD"
EXPIRING_MOVE_LOT_SERIAL = "INV-ORD-FAK-STD-1"
EXPIRING_MOVE_LOT = "LOT-ORD-FAK-01"
EXPIRING_MOVE_NEED_TAIL = "N516EV"  # already overnights at CVG
EXPIRING_MOVE_NEED_DAYS = 10

EXPIRING_REPLACE_PART = "PBE-SMOKE"
EXPIRING_REPLACE_STATION = "SDF"
EXPIRING_REPLACE_LOT_SERIAL = "INV-SDF-PBE-SMOKE-1"
EXPIRING_REPLACE_LOT = "LOT-SDF-PBE-01"

# Unscheduled-failure demo: AVIONICS-GPS installed on N508EV (DFW -> AUS).
# The closest spare (ORD) is low-confidence; the real answer is the
# already-verified spare at DFW. Left open for the "Report failure" form
# to walk through live -- not pre-resolved at seed time.
FAILURE_TAIL = "N508EV"
FAILURE_PART = "AVIONICS-GPS"
FAILURE_STATION = "AUS"
FAILURE_LOW_CONFIDENCE_SERIAL = "INV-ORD-AVIONICS-GPS-LOW"
FAILURE_VERIFIED_SERIAL = "INV-DFW-AVIONICS-GPS-GOOD"
FAILURE_REMOVAL_TAILS = ["N502EV", "N506EV", "N518EV"]  # other CRJ900s with a failure history

# A few more parts forced into the 7-day expiry window, on other tails, so
# the queue has several entries total (hero + these) instead of just one.
NEAR_EXPIRY_OVERRIDES = [
    ("N503EV", "ELT-BATT-406", 1),
    ("N508EV", "FIRE-EXT-HALON", 4),
    ("N512EV", "LIFE-VEST-ADULT", 6),
    ("N516EV", "EMK-DOC", 7),
    ("N501EV", CONNECTION_PART, CONNECTION_DAYS_TO_EXPIRY),
    (OVERSIZE_TAIL, OVERSIZE_PART, OVERSIZE_DAYS_TO_EXPIRY),
    (AOG_TAIL, AOG_PART, AOG_DAYS_TO_EXPIRY),
]

CARGO_CAPACITY_LB = {"E175": 2500.0, "CRJ900": 2200.0}


def load_fleet() -> dict:
    return json.loads(FLEET_PATH.read_text())


def seed_stations(session, fleet: dict) -> None:
    for s in fleet["stations"]:
        station = Station(**s)
        if station.code == LOW_CONFIDENCE_STATION:
            station.discrepancy_rate = LOW_CONFIDENCE_DISCREPANCY_RATE
        session.add(station)


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
        if tail in override_by_tail:
            part_no, days = override_by_tail[tail]
            if part_no not in assigned:
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
    # DG decoy: a second, serviceable ORD spare -- reachable only by the
    # one flight in the fleet that doesn't accept dangerous goods. Also
    # the low-confidence scenario: never photo-verified, moved a lot
    # recently, at a station with a discrepancy history (see
    # seed_stations above) -- below the verification threshold.
    session.add(
        InventoryItem(
            serial=f"INV-{DECOY_UNSERVICEABLE_STATION}-{HERO_PART}-2",
            part_number=HERO_PART,
            station=DECOY_UNSERVICEABLE_STATION,
            condition=InventoryCondition.serviceable,
            expires_on=TODAY + timedelta(days=400),
            last_counted_on=TODAY - timedelta(days=1),
            move_count_30d=LOW_CONFIDENCE_MOVE_COUNT_30D,
        )
    )
    # Connection scenario: the only spare is at TUL, with no direct
    # flight to CVG -- COMAT only works here via the TUL -> DFW -> CVG
    # connection.
    session.add(
        InventoryItem(
            serial=f"INV-{CONNECTION_STATION}-{CONNECTION_PART}-1",
            part_number=CONNECTION_PART,
            station=CONNECTION_STATION,
            condition=InventoryCondition.serviceable,
            expires_on=TODAY + timedelta(days=400),
            last_counted_on=TODAY - timedelta(days=1),
        )
    )
    # Oversize scenario: a serviceable spare at the aircraft's own
    # current station, so COMAT rides that aircraft's own repositioning
    # flight.
    session.add(
        InventoryItem(
            serial=f"INV-{OVERSIZE_STATION}-{OVERSIZE_PART}-1",
            part_number=OVERSIZE_PART,
            station=OVERSIZE_STATION,
            condition=InventoryCondition.serviceable,
            expires_on=TODAY + timedelta(days=400),
            last_counted_on=TODAY - timedelta(days=1),
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
        elif tail == CONNECTION_HUB_TAIL:
            # TUL -> DFW, timed to land well before EV2301 (DFW -> CVG,
            # 18:40) departs, so the TUL connection is always catchable.
            flight_number = CONNECTION_FLIGHT_NUMBER
            dep_time = time(17, 0)
            arr_time = time(17, 45)
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
                # Every seeded flight accepts DG except DG_DECOY_TAIL's --
                # the one flight in the fleet deliberately not DG-approved,
                # so an expiring DG part's candidates can show a "doesn't
                # accept dangerous goods" disqualification.
                accepts_dg=tail != DG_DECOY_TAIL,
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


def seed_shipping_requests(session) -> None:
    """A real AOG, raised directly by maintenance control -- seeded first
    so Copilot's scan (below) skips its serial rather than raising a
    duplicate, same as it would for any human-raised request."""
    station_needed = session.get(Aircraft, AOG_TAIL).overnight_station
    session.add(
        ShippingRequest(
            part_number=AOG_PART,
            serial=f"SN-{AOG_TAIL}-{AOG_PART}",
            station_needed=station_needed,
            needed_by=TODAY + timedelta(days=AOG_DAYS_TO_EXPIRY),
            priority=Priority.aog,
            raised_by=RaisedBy.maintenance_control,
            status=ShippingRequestStatus.open,
        )
    )
    session.flush()

    # Copilot's own scan: raises a request for every other part in the
    # 7-day window (hero included) -- several STDs/MRDs, none duplicating
    # the AOG above.
    raise_copilot_requests(session, window_days=7, now=datetime.now())


def seed_pick_demo(session) -> None:
    """A serviceable spare on the shelf at its expected bin, and an open
    part request a stock clerk can walk through the PickSlip flow for --
    using the seeded mismatching tag photo shows the shelf doesn't
    actually have what M3's record says."""
    session.add(
        InventoryItem(
            serial=PICK_SERIAL,
            part_number=PICK_PART,
            station=PICK_STATION,
            condition=InventoryCondition.serviceable,
            expires_on=TODAY + timedelta(days=400),
            last_counted_on=TODAY - timedelta(days=1),
            location=PICK_LOCATION,
        )
    )
    session.commit()

    get_m3_adapter().create_part_request(
        session, PICK_MECHANIC, PICK_TAIL, PICK_PART, 1, PICK_STATION, datetime.now()
    )


def seed_expiring_lots_demo(session, parts_by_number: dict) -> None:
    """Two lots M3's Expiring Lot Report would surface: one at ORD that
    CVG genuinely needs before it expires (move), and one with no demand
    anywhere, and no other spare at its own station either (replace --
    with Copilot raising a replacement request)."""
    # Move: a real need at CVG, due before the ORD lot expires.
    _add_installed_part(session, EXPIRING_MOVE_NEED_TAIL, EXPIRING_MOVE_PART, parts_by_number, EXPIRING_MOVE_NEED_DAYS)
    session.add(
        ShippingRequest(
            part_number=EXPIRING_MOVE_PART,
            serial=f"SN-{EXPIRING_MOVE_NEED_TAIL}-{EXPIRING_MOVE_PART}",
            station_needed="CVG",
            needed_by=TODAY + timedelta(days=EXPIRING_MOVE_NEED_DAYS),
            priority=Priority.std,
            raised_by=RaisedBy.maintenance_control,
            status=ShippingRequestStatus.open,
        )
    )
    session.add(
        InventoryItem(
            serial=EXPIRING_MOVE_LOT_SERIAL,
            part_number=EXPIRING_MOVE_PART,
            station=EXPIRING_MOVE_LOT_STATION,
            condition=InventoryCondition.serviceable,
            expires_on=TODAY + timedelta(days=EXPIRING_MOVE_NEED_DAYS + 2),
            last_counted_on=TODAY - timedelta(days=1),
            lot=EXPIRING_MOVE_LOT,
            location="BIN-ORD-12",
        )
    )

    # Replace: nobody needs it, and it's the only one at its station.
    session.add(
        InventoryItem(
            serial=EXPIRING_REPLACE_LOT_SERIAL,
            part_number=EXPIRING_REPLACE_PART,
            station=EXPIRING_REPLACE_STATION,
            condition=InventoryCondition.serviceable,
            expires_on=TODAY + timedelta(days=15),
            last_counted_on=TODAY - timedelta(days=1),
            lot=EXPIRING_REPLACE_LOT,
            location="BIN-SDF-03",
        )
    )
    session.commit()


def seed_failure_demo(session, parts_by_number: dict) -> None:
    """AVIONICS-GPS installed on N508EV, ready for the "Report failure"
    form: the closest spare (ORD) is low-confidence, the verified one at
    DFW is the real answer. Plus a few months of removal history --
    enough AVIONICS-GPS/CRJ900 failures elsewhere to cross the stocking
    threshold, and a couple of unrelated single removals for texture."""
    _add_installed_part(session, FAILURE_TAIL, FAILURE_PART, parts_by_number, 400)
    session.add_all(
        [
            InventoryItem(
                serial=FAILURE_LOW_CONFIDENCE_SERIAL,
                part_number=FAILURE_PART,
                station="ORD",
                condition=InventoryCondition.serviceable,
                expires_on=TODAY + timedelta(days=400),
                last_counted_on=TODAY - timedelta(days=1),
                move_count_30d=4,
            ),
            InventoryItem(
                serial=FAILURE_VERIFIED_SERIAL,
                part_number=FAILURE_PART,
                station="DFW",
                condition=InventoryCondition.serviceable,
                expires_on=TODAY + timedelta(days=400),
                last_counted_on=TODAY - timedelta(days=1),
                last_verified_at=datetime.now(),
                verified_by="Stores",
            ),
        ]
    )

    for i, tail in enumerate(FAILURE_REMOVAL_TAILS):
        session.add(
            RemovalHistory(
                part_number=FAILURE_PART,
                fleet_type="CRJ900",
                station="DFW",
                tail_number=tail,
                removed_on=TODAY - timedelta(days=85 - i * 25),
                reason=RemovalReason.failure,
            )
        )

    # Texture: a couple of unrelated, one-off removals (below the
    # stocking threshold, so they don't themselves raise a suggestion).
    session.add_all(
        [
            RemovalHistory(
                part_number="BRAKE-ASSY", fleet_type="E175", station="DFW", tail_number="N513EV",
                removed_on=TODAY - timedelta(days=45), reason=RemovalReason.scheduled,
            ),
            RemovalHistory(
                part_number="TIRE-NOSE", fleet_type="CRJ900", station="ORD", tail_number="N502EV",
                removed_on=TODAY - timedelta(days=20), reason=RemovalReason.expiry,
            ),
        ]
    )
    session.commit()


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

        seed_shipping_requests(session)
        session.commit()

        seed_pick_demo(session)
        seed_expiring_lots_demo(session, parts_by_number)
        seed_failure_demo(session, parts_by_number)

    generate_tag_images()

    print(f"Seeded comat.db: {len(fleet['stations'])} stations, "
          f"{len(fleet['aircraft'])} aircraft, {len(fleet['parts'])} parts.")


if __name__ == "__main__":
    main()
