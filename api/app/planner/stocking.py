"""Stocking suggestions: from removal history, which part/fleet-type
pairs fail often enough to be worth stocking proactively, and which
stations that operate that fleet type don't hold a spare today. A human
approves each suggestion, which raises an STD request to position one
-- the same station-level-request pattern as expiring_lots.py's
"replace" action, since positioning a spare has no specific installed
part driving it yet either.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from app.adapters.m3_adapter import get_m3_adapter
from app.config import load_settings
from app.models import (
    Aircraft,
    InventoryCondition,
    Priority,
    RaisedBy,
    RemovalHistory,
    RemovalReason,
    ShippingRequest,
    ShippingRequestStatus,
    StockingSuggestion,
    StockingSuggestionStatus,
)


class StockingSuggestionAlreadyResolved(Exception):
    """The suggestion was already approved."""


def _stations_operating(session: Session, fleet_type: str) -> set[str]:
    aircraft = session.exec(select(Aircraft).where(Aircraft.type == fleet_type)).all()
    stations = set()
    for a in aircraft:
        stations.add(a.current_station)
        stations.add(a.overnight_station)
    return stations


def _has_valid_spare(session: Session, part_number: str, station: str) -> bool:
    records = get_m3_adapter().list_stock(session, part_number=part_number, station=station)
    return any(r.condition == InventoryCondition.serviceable and not r.phantom_flag for r in records)


def scan_stocking_suggestions(session: Session, now: Optional[datetime] = None) -> list[StockingSuggestion]:
    now = now or datetime.now()
    min_failures = load_settings().stocking.min_failures_to_suggest

    failures = session.exec(select(RemovalHistory).where(RemovalHistory.reason == RemovalReason.failure)).all()
    counts = Counter((r.part_number, r.fleet_type) for r in failures)

    already = {(s.part_number, s.fleet_type, s.station) for s in session.exec(select(StockingSuggestion)).all()}

    created: list[StockingSuggestion] = []
    for (part_number, fleet_type), count in counts.items():
        if count < min_failures:
            continue
        for station in _stations_operating(session, fleet_type):
            if (part_number, fleet_type, station) in already:
                continue
            if _has_valid_spare(session, part_number, station):
                continue
            suggestion = StockingSuggestion(
                part_number=part_number,
                fleet_type=fleet_type,
                station=station,
                failure_count=count,
                reason=(
                    f"{count} {fleet_type} failures of {part_number} fleet-wide, but {station} "
                    f"(which operates {fleet_type}) holds no spare today"
                ),
                created_at=now,
            )
            session.add(suggestion)
            created.append(suggestion)

    session.commit()
    for s in created:
        session.refresh(s)
    return created


def approve_stocking_suggestion(
    session: Session, suggestion: StockingSuggestion, now: Optional[datetime] = None
) -> StockingSuggestion:
    now = now or datetime.now()
    if suggestion.status != StockingSuggestionStatus.pending:
        raise StockingSuggestionAlreadyResolved(f"stocking suggestion {suggestion.id} is already {suggestion.status.value}")

    request = ShippingRequest(
        part_number=suggestion.part_number,
        serial=None,
        station_needed=suggestion.station,
        needed_by=now.date(),
        priority=Priority.std,
        raised_by=RaisedBy.copilot,
        status=ShippingRequestStatus.open,
        created_at=now,
    )
    session.add(request)
    session.commit()
    session.refresh(request)

    suggestion.status = StockingSuggestionStatus.approved
    suggestion.approved_at = now
    suggestion.request_id = request.id
    session.add(suggestion)
    session.commit()
    session.refresh(suggestion)
    return suggestion
