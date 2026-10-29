"""Covers the hero scenario and both decoys from docs/spec.md: a serviceable
DFW spare should win via the EV2301 COMAT flight, while the unserviceable
ORD spare and the too-slow vendor quote must never surface as candidates.
"""

from app.models import PlanOption
from app.planner.candidates import build_candidates
from app.planner.score import pick_best, risk_of_slack
from tests.conftest import DEADLINE, NOW


def test_comat_flight_is_a_candidate(session, hero_part):
    candidates = build_candidates(session, hero_part, now=NOW)
    comat = [c for c in candidates if c.option == PlanOption.comat]
    assert any(c.source == "DFW" and c.flight_number == "EV2301" for c in comat)


def test_unserviceable_spare_never_becomes_a_candidate(session, hero_part):
    candidates = build_candidates(session, hero_part, now=NOW)
    assert not any(c.source == "ORD" for c in candidates)


def test_vendor_decoy_misses_deadline_and_is_dropped(session, hero_part):
    candidates = build_candidates(session, hero_part, now=NOW)
    assert not any(c.source == "SkyParts Direct" for c in candidates)


def test_legit_vendor_quote_still_makes_the_list(session, hero_part):
    candidates = build_candidates(session, hero_part, now=NOW)
    assert any(c.source == "AeroSource" and c.option == PlanOption.buy for c in candidates)


def test_best_candidate_is_the_comat_flight(session, hero_part):
    candidates = build_candidates(session, hero_part, now=NOW)
    best = pick_best(candidates, deadline=DEADLINE)
    assert best is not None
    assert best.candidate.option == PlanOption.comat
    assert best.candidate.flight_number == "EV2301"
    assert best.candidate.source == "DFW"


def test_default_candidates_are_all_feasible(session, hero_part):
    candidates = build_candidates(session, hero_part, now=NOW)
    assert candidates  # sanity: the hero case has feasible options at all
    assert not any(c.disqualified for c in candidates)


def test_disqualified_candidates_surface_with_reasons_when_requested(session, hero_part):
    candidates = build_candidates(session, hero_part, now=NOW, include_disqualified=True)

    ord_transfer = next(c for c in candidates if c.source == "ORD" and c.option == PlanOption.transfer)
    assert ord_transfer.disqualified
    assert "unserviceable" in ord_transfer.disqualified_reason

    slow_vendor = next(c for c in candidates if c.source == "SkyParts Direct")
    assert slow_vendor.disqualified
    assert "deadline" in slow_vendor.disqualified_reason

    # the winning COMAT option is still present and NOT flagged disqualified
    comat = next(c for c in candidates if c.option == PlanOption.comat and c.source == "DFW")
    assert not comat.disqualified
    assert comat.disqualified_reason is None


def test_dangerous_goods_part_flags_every_candidate(session, hero_part):
    # the hero part (crew oxygen bottle) is seeded as dangerous goods -- the
    # flag is a property of the part, so it should carry onto every option,
    # not just the winning one.
    candidates = build_candidates(session, hero_part, now=NOW, include_disqualified=True)
    assert candidates
    assert all(c.is_dangerous_goods for c in candidates)


def test_dg_part_is_disqualified_from_a_flight_that_does_not_accept_dg(session, hero_part):
    from sqlmodel import select

    from app.models import Flight

    flight = session.exec(select(Flight).where(Flight.flight_number == "EV2301")).one()
    flight.accepts_dg = False
    session.add(flight)
    session.commit()

    candidates = build_candidates(session, hero_part, now=NOW, include_disqualified=True)
    comat = next(c for c in candidates if c.source == "DFW" and c.flight_number == "EV2301")
    assert comat.disqualified
    assert "dangerous goods" in comat.disqualified_reason

    feasible = build_candidates(session, hero_part, now=NOW)
    assert not any(c.flight_number == "EV2301" for c in feasible)


def test_risk_of_slack_bounds():
    assert risk_of_slack(48) == 0.0
    assert risk_of_slack(0) == 1.0
    assert risk_of_slack(-5) == 1.0
    assert 0.0 < risk_of_slack(12) < 1.0
