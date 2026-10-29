"""Covers flight_search.py: booking cutoffs (domestic vs international),
the AOG-desk override, one-stop connections through hub stations, DG
restriction, and capacity checks.
"""

from datetime import datetime, timedelta

from app.models import Flight, FlightStatus, Part, Station
from app.planner.flight_search import leg_bookability, search_flight_options

NOW = datetime(2026, 11, 1, 8, 0)
DEADLINE = NOW + timedelta(hours=12)


def _part(**overrides):
    defaults = dict(part_number="P1", description="Test part", shelf_life_days=365, weight_lb=10)
    defaults.update(overrides)
    return Part(**defaults)


def _seed_network(session):
    session.add_all(
        [
            Station(code="AUS", name="Austin", lat=30.2, lon=-97.7, has_maintenance=False),
            Station(code="DFW", name="Dallas-Fort Worth", lat=32.9, lon=-97.0, has_maintenance=True),
            Station(code="CVG", name="Cincinnati", lat=39.0, lon=-84.7, has_maintenance=False),
        ]
    )
    session.commit()


def test_leg_outside_the_domestic_cutoff_is_bookable(session):
    flight = Flight(
        flight_number="EV1", tail_number="N1", origin="AUS", dest="CVG",
        sched_dep=NOW + timedelta(hours=2), sched_arr=NOW + timedelta(hours=4),
        cargo_capacity_lb=1000,
    )
    bookable, used_override, reason = leg_bookability(flight, NOW)
    assert bookable is True
    assert used_override is False
    assert reason is None


def test_leg_inside_the_domestic_cutoff_is_not_bookable(session):
    flight = Flight(
        flight_number="EV2", tail_number="N1", origin="AUS", dest="CVG",
        sched_dep=NOW + timedelta(minutes=30), sched_arr=NOW + timedelta(hours=2),
        cargo_capacity_lb=1000,
    )
    bookable, used_override, reason = leg_bookability(flight, NOW)
    assert bookable is False
    assert used_override is False
    assert "cutoff" in reason


def test_aog_desk_override_bypasses_the_cutoff(session):
    flight = Flight(
        flight_number="EV3", tail_number="N1", origin="AUS", dest="CVG",
        sched_dep=NOW + timedelta(minutes=30), sched_arr=NOW + timedelta(hours=2),
        cargo_capacity_lb=1000,
    )
    bookable, used_override, reason = leg_bookability(flight, NOW, aog_desk_override=True)
    assert bookable is True
    assert used_override is True
    assert reason is None


def test_international_flight_uses_the_90_minute_cutoff(session):
    # 70 minutes out: past the 60-min domestic cutoff, but still inside
    # the 90-min international one.
    flight = Flight(
        flight_number="EV4", tail_number="N1", origin="AUS", dest="CVG",
        sched_dep=NOW + timedelta(minutes=70), sched_arr=NOW + timedelta(hours=3),
        cargo_capacity_lb=1000, is_international=True,
    )
    bookable, _, reason = leg_bookability(flight, NOW)
    assert bookable is False
    assert "international" in reason


def test_direct_flight_is_found(session):
    _seed_network(session)
    session.add(
        Flight(
            flight_number="EV10", tail_number="N1", origin="AUS", dest="CVG",
            sched_dep=NOW + timedelta(hours=2), sched_arr=NOW + timedelta(hours=4),
            cargo_capacity_lb=1000,
        )
    )
    session.commit()

    options = search_flight_options(session, "AUS", "CVG", _part(), NOW, DEADLINE)

    assert len(options) == 1
    assert not options[0].is_connection
    assert options[0].legs[0].flight.flight_number == "EV10"


def test_connection_through_a_hub_is_found(session):
    _seed_network(session)
    session.add_all(
        [
            Flight(
                flight_number="EV20", tail_number="N1", origin="AUS", dest="DFW",
                sched_dep=NOW + timedelta(hours=2), sched_arr=NOW + timedelta(hours=3),
                cargo_capacity_lb=1000,
            ),
            Flight(
                flight_number="EV21", tail_number="N2", origin="DFW", dest="CVG",
                sched_dep=NOW + timedelta(hours=4), sched_arr=NOW + timedelta(hours=5),
                cargo_capacity_lb=1000,
            ),
        ]
    )
    session.commit()

    options = search_flight_options(session, "AUS", "CVG", _part(), NOW, DEADLINE)

    assert len(options) == 1
    assert options[0].is_connection
    assert options[0].hub == "DFW"
    assert [leg.flight.flight_number for leg in options[0].legs] == ["EV20", "EV21"]


def test_connection_cannot_catch_a_flight_that_leaves_before_it_lands(session):
    _seed_network(session)
    session.add_all(
        [
            Flight(
                flight_number="EV30", tail_number="N1", origin="AUS", dest="DFW",
                sched_dep=NOW + timedelta(hours=2), sched_arr=NOW + timedelta(hours=4),
                cargo_capacity_lb=1000,
            ),
            # departs before EV30 even lands at the hub
            Flight(
                flight_number="EV31", tail_number="N2", origin="DFW", dest="CVG",
                sched_dep=NOW + timedelta(hours=3), sched_arr=NOW + timedelta(hours=5),
                cargo_capacity_lb=1000,
            ),
        ]
    )
    session.commit()

    options = search_flight_options(session, "AUS", "CVG", _part(), NOW, DEADLINE)
    assert options == []


def test_second_leg_without_capacity_is_excluded(session):
    _seed_network(session)
    session.add_all(
        [
            Flight(
                flight_number="EV40", tail_number="N1", origin="AUS", dest="DFW",
                sched_dep=NOW + timedelta(hours=2), sched_arr=NOW + timedelta(hours=3),
                cargo_capacity_lb=1000,
            ),
            Flight(
                flight_number="EV41", tail_number="N2", origin="DFW", dest="CVG",
                sched_dep=NOW + timedelta(hours=4), sched_arr=NOW + timedelta(hours=5),
                cargo_capacity_lb=5,  # too small for a 10 lb part
            ),
        ]
    )
    session.commit()

    options = search_flight_options(session, "AUS", "CVG", _part(weight_lb=10), NOW, DEADLINE)
    assert options == []


def test_dg_part_only_uses_dg_accepting_flights(session):
    _seed_network(session)
    session.add_all(
        [
            Flight(
                flight_number="EV50", tail_number="N1", origin="AUS", dest="CVG",
                sched_dep=NOW + timedelta(hours=2), sched_arr=NOW + timedelta(hours=4),
                cargo_capacity_lb=1000, accepts_dg=False,
            ),
        ]
    )
    session.commit()
    dg_part = _part(is_dangerous_goods=True)

    assert search_flight_options(session, "AUS", "CVG", dg_part, NOW, DEADLINE) == []

    accepting = Flight(
        flight_number="EV51", tail_number="N2", origin="AUS", dest="CVG",
        sched_dep=NOW + timedelta(hours=2), sched_arr=NOW + timedelta(hours=4),
        cargo_capacity_lb=1000, accepts_dg=True,
    )
    session.add(accepting)
    session.commit()

    options = search_flight_options(session, "AUS", "CVG", dg_part, NOW, DEADLINE)
    assert len(options) == 1
    assert options[0].legs[0].flight.flight_number == "EV51"
