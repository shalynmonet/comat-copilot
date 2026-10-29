"""Covers api/app/config.py: it should load the committed example file
(the normal state on a fresh clone, since private_codes.yaml is
gitignored and usually absent) with the three commodity profiles and
operational parameters the rest of the app depends on.
"""

import pytest

from app.config import EXAMPLE_PATH, PRIVATE_PATH, load_private_codes


@pytest.fixture(autouse=True)
def _clear_cache():
    load_private_codes.cache_clear()
    yield
    load_private_codes.cache_clear()


def test_falls_back_to_the_example_file_when_private_is_absent():
    assert not PRIVATE_PATH.exists()  # true for every clone that hasn't set up a pilot
    codes = load_private_codes()
    assert codes.source_path == EXAMPLE_PATH


def test_all_three_commodity_profiles_are_present():
    codes = load_private_codes()
    assert set(codes.commodity_profiles) == {"critical_planeside", "critical_cargo", "low_cargo"}


def test_critical_planeside_profile():
    profile = load_private_codes().profile("critical_planeside")
    assert profile.handoff_route == "plane_side"
    assert profile.handling_codes == ["AOG", "EZP"]
    # EZP is added on save, not at creation -- it's still a listed handling
    # code, but also called out separately so callers know when to add it
    assert profile.codes_added_on_save == ["EZP"]


def test_critical_cargo_and_low_cargo_never_use_plane_side():
    codes = load_private_codes()
    assert codes.profile("critical_cargo").handoff_route == "to_cargo"
    assert codes.profile("low_cargo").handoff_route == "to_cargo"
    assert codes.profile("critical_cargo").handling_codes == ["AOG"]
    assert codes.profile("low_cargo").handling_codes == ["MRX"]


def test_operational_parameters():
    codes = load_private_codes()
    assert codes.oversize_weight_threshold_lb > 0
    assert 0 < codes.std_bump_risk < 1
    assert codes.booking_cutoff_minutes_domestic == 60
    assert codes.booking_cutoff_minutes_international == 90


def test_unknown_profile_name_raises_a_clear_error():
    codes = load_private_codes()
    with pytest.raises(KeyError, match="no commodity profile"):
        codes.profile("does-not-exist")


def test_result_is_cached(monkeypatch):
    first = load_private_codes()
    second = load_private_codes()
    assert first is second
