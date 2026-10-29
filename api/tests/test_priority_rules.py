"""Covers priority_rules.py against every rule in the spec: priority from
backup-flight count, profile/route assignment, the to_cargo/plane_side
validation guard, EZP's creation-vs-save timing, and the reason line
format (the "Plane-side: Must Ride on last viable flight." example).
"""

import pytest

from app.models import CommodityProfile, HandoffRoute, Priority
from app.planner.priority_rules import (
    ProfileRouteMismatch,
    build_reason_line,
    compute_priority,
    compute_profile_and_route,
    handling_codes_at_creation,
    handling_codes_on_save,
    is_effectively_oversize,
    priority_reason_fragment,
    validate_profile_route,
)


# ---- priority from backup flights ----

def test_std_when_at_least_one_backup_remains():
    assert compute_priority(viable_flight_count=2, part_expired=False) == Priority.std
    assert compute_priority(viable_flight_count=5, part_expired=False) == Priority.std


def test_mrd_when_the_chosen_flight_is_the_last_viable_one():
    assert compute_priority(viable_flight_count=1, part_expired=False) == Priority.mrd


def test_aog_when_none_remain_or_the_part_expired():
    assert compute_priority(viable_flight_count=0, part_expired=False) == Priority.aog
    assert compute_priority(viable_flight_count=3, part_expired=True) == Priority.aog


def test_mrx_is_never_assigned_automatically():
    for count in range(0, 5):
        for expired in (True, False):
            assert compute_priority(count, expired) != Priority.mrx


# ---- oversize ----

def test_oversize_by_explicit_flag_or_by_weight_threshold():
    assert is_effectively_oversize(is_oversize=True, weight_lb=1) is True
    assert is_effectively_oversize(is_oversize=False, weight_lb=100_000) is True
    assert is_effectively_oversize(is_oversize=False, weight_lb=1) is False


# ---- profile and route ----

def test_aog_or_mrd_normal_domestic_is_critical_planeside():
    for priority in (Priority.aog, Priority.mrd):
        profile, route = compute_profile_and_route(
            priority, is_oversize=False, is_international=False, is_ron_package=False
        )
        assert profile == CommodityProfile.critical_planeside
        assert route == HandoffRoute.plane_side


def test_aog_or_mrd_oversize_is_critical_cargo():
    profile, route = compute_profile_and_route(
        Priority.aog, is_oversize=True, is_international=False, is_ron_package=False
    )
    assert profile == CommodityProfile.critical_cargo
    assert route == HandoffRoute.to_cargo


def test_aog_or_mrd_international_is_critical_cargo():
    profile, route = compute_profile_and_route(
        Priority.mrd, is_oversize=False, is_international=True, is_ron_package=False
    )
    assert profile == CommodityProfile.critical_cargo
    assert route == HandoffRoute.to_cargo


def test_std_or_mrx_is_low_cargo():
    for priority in (Priority.std, Priority.mrx):
        profile, route = compute_profile_and_route(
            priority, is_oversize=False, is_international=False, is_ron_package=False
        )
        assert profile == CommodityProfile.low_cargo
        assert route == HandoffRoute.to_cargo


def test_ron_package_overrides_everything_to_critical_planeside():
    profile, route = compute_profile_and_route(
        Priority.std, is_oversize=True, is_international=True, is_ron_package=True
    )
    assert profile == CommodityProfile.critical_planeside
    assert route == HandoffRoute.plane_side


# ---- validation ----

def test_to_cargo_profile_cannot_be_paired_with_plane_side():
    with pytest.raises(ProfileRouteMismatch, match="to_cargo"):
        validate_profile_route(CommodityProfile.critical_cargo, HandoffRoute.plane_side)
    with pytest.raises(ProfileRouteMismatch):
        validate_profile_route(CommodityProfile.low_cargo, HandoffRoute.plane_side)


def test_matching_profile_and_route_does_not_raise():
    validate_profile_route(CommodityProfile.critical_planeside, HandoffRoute.plane_side)
    validate_profile_route(CommodityProfile.critical_cargo, HandoffRoute.to_cargo)


# ---- EZP: added on save, not at creation ----

def test_ezp_is_excluded_at_creation_for_critical_planeside():
    codes = handling_codes_at_creation(CommodityProfile.critical_planeside)
    assert "AOG" in codes
    assert "EZP" not in codes


def test_ezp_is_added_on_save():
    created = handling_codes_at_creation(CommodityProfile.critical_planeside)
    saved = handling_codes_on_save(CommodityProfile.critical_planeside, created)
    assert "EZP" in saved
    assert "AOG" in saved


def test_handling_codes_on_save_does_not_duplicate_existing_codes():
    saved = handling_codes_on_save(CommodityProfile.critical_planeside, ["AOG", "EZP"])
    assert saved.count("EZP") == 1


def test_critical_cargo_and_low_cargo_have_no_save_time_additions():
    assert handling_codes_at_creation(CommodityProfile.critical_cargo) == ["AOG"]
    assert handling_codes_on_save(CommodityProfile.critical_cargo, ["AOG"]) == ["AOG"]
    assert handling_codes_at_creation(CommodityProfile.low_cargo) == ["MRX"]


# ---- reason line ----

def test_reason_line_matches_the_spec_example():
    why = priority_reason_fragment(Priority.mrd, viable_flight_count=1, part_expired=False)
    line = build_reason_line(Priority.mrd, HandoffRoute.plane_side, why)
    assert line == "Plane-side: Must Ride on last viable flight."


def test_reason_line_for_std_names_the_backup_count():
    why = priority_reason_fragment(Priority.std, viable_flight_count=3, part_expired=False)
    assert "2 backup flights" in why
    line = build_reason_line(Priority.std, HandoffRoute.to_cargo, why)
    assert line == "Cargo: Standard with 2 backup flights still available."


def test_reason_line_for_a_single_backup_uses_singular():
    why = priority_reason_fragment(Priority.std, viable_flight_count=2, part_expired=False)
    assert "1 backup flight " in why
    assert "flights" not in why


def test_reason_line_for_expired_part():
    why = priority_reason_fragment(Priority.aog, viable_flight_count=0, part_expired=True)
    assert why == "the part has already expired"
