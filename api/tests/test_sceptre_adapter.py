"""Covers the mock Sceptre (parts & expiry) adapter: it should answer the
same question the live /parts/expiring route needs, and the swap point
(get_parts_adapter / PARTS_ADAPTER) should behave as documented.
"""

from datetime import date, timedelta

import pytest

from app.adapters.sceptre_adapter import MockSceptreAdapter, get_parts_adapter
from app.models import Aircraft, InstalledPart, Part


@pytest.fixture()
def two_parts(session):
    today = date.today()
    session.add_all(
        [
            Aircraft(tail_number="N501EV", type="E175", current_station="CVG", overnight_station="CVG"),
            Part(
                part_number="OXY-BTL-02",
                description="Crew Oxygen Bottle, 2L",
                shelf_life_days=730,
                is_rotable=False,
                unit_cost=850,
                weight_lb=18,
                is_dangerous_goods=True,
            ),
            Part(
                part_number="FAK-STD",
                description="First Aid Kit, Standard",
                shelf_life_days=730,
                is_rotable=False,
                unit_cost=95,
                weight_lb=3,
            ),
            InstalledPart(
                serial="SN-EXPIRING",
                part_number="OXY-BTL-02",
                tail_number="N501EV",
                position="OXY-CREW-1",
                installed_on=today - timedelta(days=700),
                expires_on=today + timedelta(days=2),
            ),
            InstalledPart(
                serial="SN-FAR-OUT",
                part_number="FAK-STD",
                tail_number="N501EV",
                position="CABIN-FAK",
                installed_on=today - timedelta(days=10),
                expires_on=today + timedelta(days=400),
            ),
        ]
    )
    session.commit()
    return today


def test_lists_only_parts_inside_the_window(session, two_parts):
    today = two_parts
    records = MockSceptreAdapter().list_expiring(session, window_days=7, today=today)

    assert len(records) == 1
    assert records[0].serial == "SN-EXPIRING"
    assert records[0].station == "CVG"
    assert records[0].is_dangerous_goods is True


def test_get_parts_adapter_defaults_to_mock(monkeypatch):
    monkeypatch.delenv("PARTS_ADAPTER", raising=False)
    assert isinstance(get_parts_adapter(), MockSceptreAdapter)


def test_get_parts_adapter_is_the_documented_pilot_swap_point(monkeypatch):
    monkeypatch.setenv("PARTS_ADAPTER", "sceptre")
    with pytest.raises(NotImplementedError, match="sceptre"):
        get_parts_adapter()
