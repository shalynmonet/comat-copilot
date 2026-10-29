"""Priority, commodity profile, and handoff-route rules.

Priority comes from how many viable backup flights exist: plenty of room
to be relaxed (STD), none left so this one can't be bumped (MRD), or
none viable at all / the part's already expired (AOG). MRX only ever
comes from a human picking it -- nothing in here returns it.

Profile and route follow from priority plus the part's own properties
(oversize, international, overnight-stay replacement); the generic
profile names are hardcoded here since they're just internal
identifiers, but the route and handling codes behind each one come from
api/config/private_codes.yaml (see app/config.py) -- the one place a
pilot's real codes live.

assign_priority_profile_route() is the integration point: it populates
these fields directly on a Plan, right before a SAFE draft is built from
it (see app/adapters/safe_adapter.py and app/planner/decisions.py).
compute_priority_assignment() is the same computation without needing a
real Plan -- replan.py uses it to describe what a *pending* recommendation
would be (priority included) before anyone has approved it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional

from sqlmodel import Session, select

from app.config import load_private_codes
from app.models import Aircraft, CommodityProfile, Flight, HandoffRoute, InstalledPart, Part, Plan, PlanOption, Priority
from app.planner.flight_search import search_flight_options

PRIORITY_RANK = {Priority.std: 0, Priority.mrx: 0, Priority.mrd: 1, Priority.aog: 2}

PRIORITY_LABELS = {
    Priority.aog: "AOG",
    Priority.mrd: "Must Ride",
    Priority.mrx: "MRX",
    Priority.std: "Standard",
}

ROUTE_LABELS = {
    HandoffRoute.plane_side: "Plane-side",
    HandoffRoute.to_cargo: "Cargo",
}


class ProfileRouteMismatch(ValueError):
    """A commodity profile was paired with a handoff route its own config
    doesn't allow -- most importantly, a to_cargo profile with plane_side."""


def compute_priority(viable_flight_count: int, part_expired: bool) -> Priority:
    """viable_flight_count is how many bookable flight options (from
    flight_search.search_flight_options) would still arrive before the
    deadline -- including whichever one ends up chosen. MRX is never
    returned here; it's always a manual pick."""
    if part_expired or viable_flight_count == 0:
        return Priority.aog
    if viable_flight_count == 1:
        return Priority.mrd
    return Priority.std


def is_effectively_oversize(*, is_oversize: bool, weight_lb: float) -> bool:
    threshold = load_private_codes().oversize_weight_threshold_lb
    return is_oversize or weight_lb >= threshold


def compute_profile_and_route(
    priority: Priority,
    *,
    is_oversize: bool,
    is_international: bool,
    is_ron_package: bool,
) -> tuple[CommodityProfile, HandoffRoute]:
    if is_ron_package:
        profile = CommodityProfile.critical_planeside
    elif priority in (Priority.aog, Priority.mrd):
        profile = (
            CommodityProfile.critical_cargo
            if (is_oversize or is_international)
            else CommodityProfile.critical_planeside
        )
    else:  # STD or MRX
        profile = CommodityProfile.low_cargo

    route = HandoffRoute(load_private_codes().profile(profile.value).handoff_route)
    validate_profile_route(profile, route)
    return profile, route


def validate_profile_route(profile: CommodityProfile, route: HandoffRoute) -> None:
    expected = HandoffRoute(load_private_codes().profile(profile.value).handoff_route)
    if route != expected:
        if route == HandoffRoute.plane_side and expected == HandoffRoute.to_cargo:
            raise ProfileRouteMismatch(
                f"{profile.value} is a to_cargo-only profile and cannot be paired with plane_side"
            )
        raise ProfileRouteMismatch(
            f"{profile.value} expects handoff_route={expected.value}, got {route.value}"
        )


def handling_codes_at_creation(profile: CommodityProfile) -> list[str]:
    """Codes to set when the plan/candidate is first built. Any code
    listed under codes_added_on_save (e.g. EZP) is deliberately left off
    until the shipment is actually saved."""
    cfg = load_private_codes().profile(profile.value)
    return [c for c in cfg.handling_codes if c not in cfg.codes_added_on_save]


def handling_codes_on_save(profile: CommodityProfile, existing_codes: list[str]) -> list[str]:
    """Codes to use once the shipment is saved -- appends whatever
    codes_added_on_save lists (e.g. EZP) if not already present."""
    cfg = load_private_codes().profile(profile.value)
    codes = list(existing_codes)
    for code in cfg.codes_added_on_save:
        if code not in codes:
            codes.append(code)
    return codes


def priority_reason_fragment(priority: Priority, viable_flight_count: int, part_expired: bool) -> str:
    if part_expired:
        return "the part has already expired"
    if priority == Priority.aog:
        return "no viable flight remains"
    if priority == Priority.mrd:
        return "on last viable flight"
    if priority == Priority.std:
        backups = max(viable_flight_count - 1, 0)
        return f"with {backups} backup flight{'s' if backups != 1 else ''} still available"
    return "picked manually"  # MRX


def build_reason_line(priority: Priority, route: HandoffRoute, why: str) -> str:
    return f"{ROUTE_LABELS[route]}: {PRIORITY_LABELS[priority]} {why}."


@dataclass
class PriorityAssignment:
    priority: Priority
    commodity_profile: CommodityProfile
    handoff_route: HandoffRoute
    handling_codes: list[str]
    viable_flight_count: int
    part_expired: bool


def compute_priority_assignment(
    session: Session,
    installed: InstalledPart,
    part: Part,
    option: PlanOption,
    source: Optional[str],
    flight_number: Optional[str],
    is_ron_package: bool,
    now: datetime,
) -> PriorityAssignment:
    """The pure version of assign_priority_profile_route(): takes the
    option/source/flight_number explicitly instead of reading them off a
    Plan, so it can describe a *candidate* recommendation -- not yet
    committed to any Plan -- just as well as a real one. Only COMAT gets
    a flight-backup-based priority (that's the only option with
    "flights" to count); transfer/buy default to STD unless the part has
    expired.
    """
    part_expired = installed.expires_on < now.date()

    is_international = False
    viable_flight_count = 0
    if option == PlanOption.comat and flight_number:
        aircraft = session.get(Aircraft, installed.tail_number)
        deadline = datetime.combine(installed.expires_on, time.min)
        viable = search_flight_options(session, source, aircraft.overnight_station, part, now, deadline)
        viable_flight_count = len(viable)
        priority = compute_priority(viable_flight_count, part_expired)

        flight = session.exec(select(Flight).where(Flight.flight_number == flight_number)).first()
        is_international = bool(flight and flight.is_international)
    else:
        priority = Priority.aog if part_expired else Priority.std

    oversize = is_effectively_oversize(is_oversize=part.is_oversize, weight_lb=part.weight_lb)
    profile, route = compute_profile_and_route(
        priority, is_oversize=oversize, is_international=is_international, is_ron_package=is_ron_package
    )

    return PriorityAssignment(
        priority=priority,
        commodity_profile=profile,
        handoff_route=route,
        handling_codes=handling_codes_at_creation(profile),
        viable_flight_count=viable_flight_count,
        part_expired=part_expired,
    )


def assign_priority_profile_route(session: Session, plan: Plan, now: datetime) -> PriorityAssignment:
    """Computes priority/commodity_profile/handoff_route/handling_codes
    for whatever option is currently on `plan` and sets them directly."""
    installed = session.get(InstalledPart, plan.installed_serial)
    part = session.get(Part, installed.part_number)
    assignment = compute_priority_assignment(
        session, installed, part, plan.option, plan.source, plan.flight_number, plan.is_ron_package, now
    )

    plan.priority = assignment.priority
    plan.commodity_profile = assignment.commodity_profile
    plan.handoff_route = assignment.handoff_route
    plan.handling_codes = assignment.handling_codes
    return assignment
