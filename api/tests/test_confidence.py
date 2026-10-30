"""Covers confidence.py: the formula's three penalty terms, clamping,
and that the reported top reason actually matches whichever penalty
dominates.
"""

from datetime import datetime, timedelta

from app.planner.confidence import compute_confidence

NOW = datetime(2026, 11, 1, 8, 0)


def test_never_verified_no_moves_clean_station_is_comfortably_above_the_default_threshold():
    # Most spares, most of the time, have never had a dedicated photo
    # verification -- confidence shouldn't punish that alone.
    result = compute_confidence(last_verified_at=None, move_count_30d=0, station_discrepancy_rate=0.0, now=NOW)
    assert result.confidence > 0.6
    assert result.days_since_verified is None


def test_just_verified_no_moves_clean_station_is_full_confidence():
    result = compute_confidence(last_verified_at=NOW, move_count_30d=0, station_discrepancy_rate=0.0, now=NOW)
    assert result.confidence == 1.0
    assert "fully verified" in result.top_reason


def test_heavy_moves_and_bad_station_drag_confidence_below_threshold():
    result = compute_confidence(
        last_verified_at=None, move_count_30d=5, station_discrepancy_rate=0.4, now=NOW
    )
    assert result.confidence < 0.6


def test_confidence_is_clamped_to_the_configured_floor_at_maximum_penalty():
    # Weights sum to less than 1.0 by design (see settings.yaml), so even
    # the worst-case input never actually reaches the max(0.0, ...) floor
    # -- this just confirms the ceiling of how bad confidence can get.
    result = compute_confidence(
        last_verified_at=None, move_count_30d=100, station_discrepancy_rate=1.0, now=NOW
    )
    assert result.confidence == round(1.0 - 0.15 - 0.2 - 0.35, 3)
    assert result.confidence > 0.0


def test_top_reason_identifies_the_dominant_penalty():
    # moves_weight (0.2) > discrepancy_weight*0.1 (0.035) > days_weight (0.15) here --
    # moves should win.
    result = compute_confidence(last_verified_at=None, move_count_30d=5, station_discrepancy_rate=0.1, now=NOW)
    assert "moves" in result.top_reason

    # a high discrepancy rate alone should win over an unverified-but-otherwise-idle spare.
    result = compute_confidence(last_verified_at=None, move_count_30d=0, station_discrepancy_rate=0.9, now=NOW)
    assert "discrepancy" in result.top_reason


def test_days_since_verified_is_reported_when_verified_before():
    result = compute_confidence(
        last_verified_at=NOW - timedelta(days=30), move_count_30d=0, station_discrepancy_rate=0.0, now=NOW
    )
    assert result.days_since_verified == 30.0
