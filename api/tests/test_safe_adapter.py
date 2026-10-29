"""Covers safe_adapter.py directly: the field list loads, and build_draft
fills every field it can from a plan -- condition inferred from the
option, PALs from the origin/destination stations, missing required
fields correctly keep status at "draft".
"""

from datetime import date, datetime, timedelta

import pytest

from app.adapters.safe_adapter import build_draft, load_field_specs
from app.models import (
    Aircraft,
    CommodityProfile,
    HandoffRoute,
    InstalledPart,
    Part,
    Plan,
    PlanOption,
    PlanStatus,
    Priority,
    Station,
)


def test_field_specs_load_and_cover_every_spec_field():
    specs = load_field_specs()
    names = {s.name for s in specs}
    assert names == {
        "part_number", "serial", "description", "quantity", "condition",
        "origin_station", "dest_station", "flight_legs", "flight_date",
        "tail_number", "priority", "commodity_profile", "handling_codes",
        "handoff_route", "is_dangerous_goods", "dg_class", "weight_lb",
        "agent_pal", "shipper_pal", "consignee_pal", "awb_number",
        "requested_by", "notes",
    }


@pytest.fixture()
def world(session):
    today = date.today()
    session.add_all(
        [
            Station(code="DFW", name="Dallas-Fort Worth", lat=32.9, lon=-97.0, pal_number="PAL-DFW"),
            Station(code="CVG", name="Cincinnati", lat=39.0, lon=-84.7, pal_number="PAL-CVG"),
            Aircraft(tail_number="N501EV", type="E175", current_station="CVG", overnight_station="CVG"),
            Part(
                part_number="OXY-BTL-02", description="Crew Oxygen Bottle, 2L", shelf_life_days=730,
                unit_cost=850, weight_lb=18, is_dangerous_goods=True, dg_class="2.2",
            ),
            InstalledPart(
                serial="SN-1", part_number="OXY-BTL-02", tail_number="N501EV", position="OXY-CREW-1",
                installed_on=today, expires_on=today + timedelta(days=2),
            ),
        ]
    )
    session.commit()
    return today


def test_build_draft_is_ready_when_every_required_field_is_known(session, world):
    plan = Plan(
        installed_serial="SN-1", option=PlanOption.comat, source="DFW", flight_number=None,
        cost=25.0, risk_score=0.0, status=PlanStatus.approved,
        priority=Priority.mrd, commodity_profile=CommodityProfile.critical_planeside,
        handoff_route=HandoffRoute.plane_side, handling_codes=["AOG"],
    )
    session.add(plan)
    session.commit()
    session.refresh(plan)

    result = build_draft(session, plan)

    assert result.status == "ready"
    assert result.missing_fields == []
    assert result.fields["condition"] == "serviceable"
    assert result.fields["agent_pal"] == "PAL-DFW"
    assert result.fields["shipper_pal"] == "PAL-DFW"
    assert result.fields["consignee_pal"] == "PAL-CVG"
    assert result.fields["is_dangerous_goods"] is True
    assert result.fields["dg_class"] == "2.2"
    assert result.fields["handling_codes"] == ["AOG"]


def test_build_draft_stays_a_draft_when_priority_was_never_assigned(session, world):
    # priority/profile/route haven't been set on this plan yet
    plan = Plan(installed_serial="SN-1", option=PlanOption.comat, source="DFW", cost=25.0, risk_score=0.0)
    session.add(plan)
    session.commit()
    session.refresh(plan)

    result = build_draft(session, plan)

    assert result.status == "draft"
    assert "priority" in result.missing_fields
    assert "commodity_profile" in result.missing_fields
    assert "handoff_route" in result.missing_fields


def test_buy_plan_gets_new_condition_and_no_station_pals(session, world):
    plan = Plan(
        installed_serial="SN-1", option=PlanOption.buy, source="AeroSource", cost=930.0, risk_score=0.1,
        priority=Priority.std, commodity_profile=CommodityProfile.low_cargo, handoff_route=HandoffRoute.to_cargo,
        handling_codes=["MRX"],
    )
    session.add(plan)
    session.commit()
    session.refresh(plan)

    result = build_draft(session, plan)

    assert result.fields["condition"] == "new"
    assert result.fields["origin_station"] == "AeroSource"
    assert result.fields["agent_pal"] is None
    assert "agent_pal" in result.missing_fields
    assert result.status == "draft"
