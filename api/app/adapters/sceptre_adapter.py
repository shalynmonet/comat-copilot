"""Parts & expiry adapter.

Knowing what's installed where, and when it expires, normally comes from a
fleet records / MRO system -- Sceptre, in a pilot. Today there's no Sceptre
account to call, so `MockSceptreAdapter` answers the same question from our
own seeded InstalledPart/Part data instead. `list_expiring()` in, a list of
`ExpiringPartRecord` out, either way: a pilot sets `PARTS_ADAPTER=sceptre`,
registers a real client with the same method, and nothing that calls this
module changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from sqlmodel import Session, select

from app.models import Aircraft, InstalledPart, Part


@dataclass
class ExpiringPartRecord:
    serial: str
    part_number: str
    description: str
    tail_number: str
    station: str
    position: str
    expires_on: date
    is_dangerous_goods: bool


class PartsAdapter(Protocol):
    def list_expiring(self, session: Session, window_days: int, today: date) -> list[ExpiringPartRecord]: ...


class MockSceptreAdapter:
    """Stands in for Sceptre. Joins our own InstalledPart/Part/Aircraft
    tables -- the same installed-parts-and-expiry-dates data a fleet
    records system holds -- instead of calling out to one."""

    source = "mock"

    def list_expiring(self, session: Session, window_days: int, today: date) -> list[ExpiringPartRecord]:
        installed = session.exec(select(InstalledPart)).all()
        parts_by_number = {p.part_number: p for p in session.exec(select(Part)).all()}
        aircraft_by_tail = {a.tail_number: a for a in session.exec(select(Aircraft)).all()}

        out = []
        for ip in installed:
            days_left = (ip.expires_on - today).days
            if days_left > window_days:
                continue
            part = parts_by_number.get(ip.part_number)
            aircraft = aircraft_by_tail.get(ip.tail_number)
            out.append(
                ExpiringPartRecord(
                    serial=ip.serial,
                    part_number=ip.part_number,
                    description=part.description if part else "",
                    tail_number=ip.tail_number,
                    station=aircraft.overnight_station if aircraft else "",
                    position=ip.position,
                    expires_on=ip.expires_on,
                    is_dangerous_goods=part.is_dangerous_goods if part else False,
                )
            )
        out.sort(key=lambda r: r.expires_on)
        return out


def get_parts_adapter() -> PartsAdapter:
    """The pilot swap point: set PARTS_ADAPTER=sceptre and register a class
    here with the same list_expiring() signature, pointed at real
    credentials. Nothing that calls get_parts_adapter() has to change."""
    backend = os.environ.get("PARTS_ADAPTER", "mock")
    if backend == "mock":
        return MockSceptreAdapter()
    raise NotImplementedError(
        f"PARTS_ADAPTER={backend!r} isn't wired up yet -- implement a PartsAdapter "
        "for it and register it in get_parts_adapter()."
    )
