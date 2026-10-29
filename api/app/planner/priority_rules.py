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

This module only computes; it doesn't attach these values to a Plan or
Candidate yet. That wiring happens once a concrete flow (building a
shipment draft, say) needs it -- see the step this was built for.
"""

from __future__ import annotations

from app.config import load_private_codes
from app.models import CommodityProfile, HandoffRoute, Priority

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
