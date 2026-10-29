"""Covers the mock shipping-ticket adapter: a plain ticket for a plain
part, a dangerous-goods note when the part needs one, and the swap point
(get_shipping_adapter / SHIPPING_ADAPTER) behaves as documented.
"""

import pytest

from app.adapters.shipping_adapter import (
    MockShippingAdapter,
    ShippingTicketRequest,
    get_shipping_adapter,
)


def _request(**overrides) -> ShippingTicketRequest:
    defaults = dict(
        plan_id=1,
        option="COMAT",
        part_number="OXY-BTL-02",
        part_description="Crew Oxygen Bottle, 2L",
        serial="SN-N501EV-OXY-BTL-02",
        source="DFW",
        destination="CVG",
        flight_number="EV2301",
        is_dangerous_goods=False,
    )
    defaults.update(overrides)
    return ShippingTicketRequest(**defaults)


def test_creates_a_ticket_and_work_order():
    ticket = MockShippingAdapter().create_ticket(_request())

    assert ticket.ticket_number.startswith("TCK-")
    assert ticket.work_order_number.startswith("WO-")
    assert ticket.special_handling == []
    assert "DFW -> CVG" in ticket.detail
    assert "EV2301" in ticket.detail


def test_flags_dangerous_goods_on_the_ticket():
    ticket = MockShippingAdapter().create_ticket(_request(is_dangerous_goods=True))

    assert any("DANGEROUS GOODS" in note for note in ticket.special_handling)


def test_works_without_a_flight_or_source_station():
    # a buy option has no source station and no flight
    ticket = MockShippingAdapter().create_ticket(_request(option="buy", source=None, flight_number=None))

    assert "EV2301" not in ticket.detail
    assert "CVG" in ticket.detail


def test_get_shipping_adapter_defaults_to_mock(monkeypatch):
    monkeypatch.delenv("SHIPPING_ADAPTER", raising=False)
    assert isinstance(get_shipping_adapter(), MockShippingAdapter)


def test_get_shipping_adapter_is_the_documented_pilot_swap_point(monkeypatch):
    monkeypatch.setenv("SHIPPING_ADAPTER", "real-carrier-system")
    with pytest.raises(NotImplementedError, match="real-carrier-system"):
        get_shipping_adapter()
