"""Stock-by-station adapter, and the digital pick-and-issue flow.

Today's pick-and-issue runs through M3: a mechanic brings a parts list,
the stock clerk creates a part request, picks the part using a paper
PickSlip, hand-writes location and serial, then retypes them into M3 to
complete the issue. This adapter is what M3 would answer and do for
that -- where a part sits station by station (list_stock/
get_expected_stock), opening a request (create_part_request), and
completing an issue once a photo confirms the pick (complete_issue).
get_expiring_lots() is M3's Expiring Lot Report -- the source of truth
for shelf-life here, not a parallel shelf-life tracker of our own.
SCEPTRE stays the source for installed parts and expiry (see
sceptre_adapter.py). `MockM3Adapter` answers and acts against our own
seeded InventoryItem/PartRequest tables, with the same confidence-
relevant facts (last_verified_at, move_count_30d) a real M3 pull would
carry. Every method here in, the same shape out, either way: a pilot
sets M3_ADAPTER=m3, registers a real client with the same signatures,
and nothing that calls this module changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional, Protocol

from sqlmodel import Session, select

from app.models import InventoryCondition, InventoryItem, PartRequest, PartRequestStatus


@dataclass
class StockRecord:
    serial: str
    part_number: str
    station: str
    location: Optional[str]
    lot: str
    expires_on: date
    condition: InventoryCondition
    last_verified_at: Optional[datetime]
    verified_by: Optional[str]
    move_count_30d: int
    phantom_flag: bool


class StockAdapter(Protocol):
    def list_stock(
        self, session: Session, part_number: Optional[str] = None, station: Optional[str] = None
    ) -> list[StockRecord]: ...

    def get_expected_stock(self, session: Session, part_number: str, station: str) -> list[StockRecord]: ...

    def get_expiring_lots(self, session: Session, window_days: int) -> list[StockRecord]: ...

    def create_part_request(
        self,
        session: Session,
        mechanic: str,
        tail_number: str,
        part_number: str,
        quantity: int,
        station: str,
        now: datetime,
    ) -> PartRequest: ...

    def complete_issue(
        self, session: Session, request: PartRequest, picked_location: Optional[str], picked_serial: str, now: datetime
    ) -> PartRequest: ...


class MockM3Adapter:
    """Stands in for M3. Joins our own seeded InventoryItem table for
    stock, and directly manages our own PartRequest table for requests
    and issues -- the same records a real M3 integration would read and
    write."""

    source = "mock"

    def list_stock(
        self, session: Session, part_number: Optional[str] = None, station: Optional[str] = None
    ) -> list[StockRecord]:
        query = select(InventoryItem)
        if part_number is not None:
            query = query.where(InventoryItem.part_number == part_number)
        if station is not None:
            query = query.where(InventoryItem.station == station)

        return [
            StockRecord(
                serial=item.serial,
                part_number=item.part_number,
                station=item.station,
                location=item.location,
                lot=item.lot or item.serial,
                expires_on=item.expires_on,
                condition=item.condition,
                last_verified_at=item.last_verified_at,
                verified_by=item.verified_by,
                move_count_30d=item.move_count_30d,
                phantom_flag=item.phantom_flag,
            )
            for item in session.exec(query).all()
        ]

    def get_expected_stock(self, session: Session, part_number: str, station: str) -> list[StockRecord]:
        """What M3's own records say is at this station -- serviceable
        stock first (since that's what a pick would actually be sent
        after), then the soonest-expiring lot among those, so a pick
        naturally uses up shelf life that's about to be wasted anyway.
        Includes phantom-flagged rows: M3 doesn't know a record is wrong
        until a photo proves it."""
        records = self.list_stock(session, part_number=part_number, station=station)
        return sorted(records, key=lambda r: (r.condition != InventoryCondition.serviceable, r.expires_on))

    def get_expiring_lots(self, session: Session, window_days: int) -> list[StockRecord]:
        """M3's Expiring Lot Report: serviceable, not-yet-flagged stock
        expiring within the window, run on a schedule (configurable,
        default daily -- see app/planner/expiring_lots.py) the same way
        M3 pushes this report automatically in a pilot."""
        horizon = date.today() + timedelta(days=window_days)
        records = self.list_stock(session)
        return sorted(
            (
                r
                for r in records
                if r.condition == InventoryCondition.serviceable and not r.phantom_flag and r.expires_on <= horizon
            ),
            key=lambda r: r.expires_on,
        )

    def create_part_request(
        self,
        session: Session,
        mechanic: str,
        tail_number: str,
        part_number: str,
        quantity: int,
        station: str,
        now: datetime,
    ) -> PartRequest:
        expected = next(
            (r for r in self.get_expected_stock(session, part_number, station) if not r.phantom_flag), None
        )
        request = PartRequest(
            mechanic=mechanic,
            tail_number=tail_number,
            part_number=part_number,
            quantity=quantity,
            station=station,
            status=PartRequestStatus.open,
            expected_location=expected.location if expected else None,
            expected_serial=expected.serial if expected else None,
            created_at=now,
        )
        session.add(request)
        session.commit()
        session.refresh(request)
        return request

    def complete_issue(
        self, session: Session, request: PartRequest, picked_location: Optional[str], picked_serial: str, now: datetime
    ) -> PartRequest:
        request.picked_location = picked_location
        request.picked_serial = picked_serial
        request.status = PartRequestStatus.issued
        request.picked_at = now
        request.issued_at = now
        session.add(request)
        session.commit()
        session.refresh(request)
        return request


def get_m3_adapter() -> StockAdapter:
    """The pilot swap point: set M3_ADAPTER=m3 and register a real client
    here with the same method signatures. Nothing that calls
    get_m3_adapter() has to change."""
    backend = os.environ.get("M3_ADAPTER", "mock")
    if backend == "mock":
        return MockM3Adapter()
    raise NotImplementedError(f"M3_ADAPTER={backend!r} isn't wired up yet -- implement a StockAdapter for it.")
