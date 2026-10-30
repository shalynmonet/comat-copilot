"""Inventory confidence: how much to trust that a spare is actually where
the record says it is. Many AOGs happen because a station's records show
a valid spare that isn't really there -- this is Copilot's early check
against that, not a black box: confidence is a simple weighted formula
over three explainable facts (days since the spare was last physically
verified, how often it's moved recently, and the station's own track
record of discrepancies), so Stores can always see exactly why a source
is flagged. Weights live in config/settings.yaml.

compute_confidence() is pure (no DB writes) -- candidates.py calls it on
every spare to score and display confidence live, so it never reads a
stale cached value. refresh_confidence() is the one place that writes
the cached InventoryItem.confidence column, called whenever something
that feeds the formula actually changes (seeding, a verify_task
resolving).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlmodel import Session

from app.config import load_settings
from app.models import InventoryItem, Station


@dataclass
class ConfidenceResult:
    confidence: float
    top_reason: str
    days_since_verified: Optional[float]


def compute_confidence(
    *,
    last_verified_at: Optional[datetime],
    move_count_30d: int,
    station_discrepancy_rate: float,
    now: datetime,
) -> ConfidenceResult:
    settings = load_settings().confidence

    if last_verified_at is None:
        days_since_verified = None
        days_fraction = 1.0  # never verified -- treat like it's fully stale
    else:
        days_since_verified = max((now - last_verified_at).total_seconds() / 86400, 0.0)
        days_fraction = min(days_since_verified / settings.days_horizon, 1.0)

    moves_fraction = min(move_count_30d / settings.moves_cap, 1.0) if settings.moves_cap else 0.0
    discrepancy_fraction = min(max(station_discrepancy_rate, 0.0), 1.0)

    days_penalty = settings.days_weight * days_fraction
    moves_penalty = settings.moves_weight * moves_fraction
    discrepancy_penalty = settings.discrepancy_weight * discrepancy_fraction

    confidence = max(0.0, min(1.0, settings.base - days_penalty - moves_penalty - discrepancy_penalty))

    verified_text = "never verified" if last_verified_at is None else f"last verified {days_since_verified:.0f} days ago"
    reasons = [
        (days_penalty, verified_text),
        (moves_penalty, f"{move_count_30d} move{'s' if move_count_30d != 1 else ''} in the last 30 days"),
        (discrepancy_penalty, f"station discrepancy rate {station_discrepancy_rate:.0%}"),
    ]
    top_penalty, top_reason = max(reasons, key=lambda r: r[0])
    if top_penalty <= 0:
        top_reason = "fully verified, no recent moves, clean station record"

    return ConfidenceResult(
        confidence=round(confidence, 3), top_reason=top_reason, days_since_verified=days_since_verified
    )


def confidence_for_item(session: Session, item: InventoryItem, now: datetime) -> ConfidenceResult:
    station = session.get(Station, item.station)
    return compute_confidence(
        last_verified_at=item.last_verified_at,
        move_count_30d=item.move_count_30d,
        station_discrepancy_rate=station.discrepancy_rate if station else 0.0,
        now=now,
    )


def refresh_confidence(session: Session, item: InventoryItem, now: datetime) -> ConfidenceResult:
    """Recomputes and persists item.confidence -- call this whenever
    something that feeds the formula changes (not on every read)."""
    result = confidence_for_item(session, item, now)
    item.confidence = result.confidence
    session.add(item)
    return result


def bump_station_discrepancy_rate(session: Session, station: Station) -> None:
    bump = load_settings().confidence.discrepancy_bump
    station.discrepancy_rate = min(1.0, station.discrepancy_rate + bump)
    session.add(station)
