"""Loads the pilot's private commodity-profile codes, oversize threshold,
STD bump risk, and booking cutoffs from config/private_codes.yaml.

That file is gitignored -- real internal codes (handling codes, exact
cutoffs) never reach the repo. A fresh clone has no private_codes.yaml,
so this falls back to config/private_codes.example.yaml (placeholder
values) and logs that it did, meaning the app still runs correctly out
of the box. For a pilot, copy the example, fill in real values, and
nothing in code has to change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
PRIVATE_PATH = CONFIG_DIR / "private_codes.yaml"
EXAMPLE_PATH = CONFIG_DIR / "private_codes.example.yaml"
SETTINGS_PATH = CONFIG_DIR / "settings.yaml"


@dataclass
class CommodityProfile:
    name: str
    handoff_route: str  # "plane_side" | "to_cargo"
    handling_codes: list[str]
    codes_added_on_save: list[str]


@dataclass
class PrivateCodes:
    commodity_profiles: dict[str, CommodityProfile]
    oversize_weight_threshold_lb: float
    std_bump_risk: float
    booking_cutoff_minutes_domestic: int
    booking_cutoff_minutes_international: int
    source_path: Path

    def profile(self, name: str) -> CommodityProfile:
        try:
            return self.commodity_profiles[name]
        except KeyError:
            raise KeyError(
                f"no commodity profile {name!r} in {self.source_path} "
                f"(have: {', '.join(self.commodity_profiles)})"
            ) from None


def _parse(path: Path) -> PrivateCodes:
    raw = yaml.safe_load(path.read_text())
    profiles = {
        key: CommodityProfile(
            name=key,
            handoff_route=value["handoff_route"],
            handling_codes=list(value.get("handling_codes", [])),
            codes_added_on_save=list(value.get("codes_added_on_save", [])),
        )
        for key, value in raw["commodity_profiles"].items()
    }
    cutoffs = raw["booking_cutoffs_minutes"]
    return PrivateCodes(
        commodity_profiles=profiles,
        oversize_weight_threshold_lb=float(raw["oversize_weight_threshold_lb"]),
        std_bump_risk=float(raw["std_bump_risk"]),
        booking_cutoff_minutes_domestic=int(cutoffs["domestic"]),
        booking_cutoff_minutes_international=int(cutoffs["international"]),
        source_path=path,
    )


@lru_cache(maxsize=1)
def load_private_codes() -> PrivateCodes:
    if PRIVATE_PATH.exists():
        return _parse(PRIVATE_PATH)
    logger.warning(
        "api/config/private_codes.yaml not found; using placeholder values from "
        "private_codes.example.yaml. Copy the example and fill in real codes before a pilot."
    )
    return _parse(EXAMPLE_PATH)


@dataclass
class ConfidenceSettings:
    base: float
    days_weight: float
    days_horizon: float
    moves_weight: float
    moves_cap: float
    discrepancy_weight: float
    verification_threshold: float
    discrepancy_bump: float
    confidence_score_weight: float


@dataclass
class ExpiringLotSettings:
    window_days: int
    scan_schedule: str


@dataclass
class FailureSettings:
    verify_time_buffer_minutes: int


@dataclass
class StockingSettings:
    min_failures_to_suggest: int


@dataclass
class Settings:
    confidence: ConfidenceSettings
    expiring_lots: ExpiringLotSettings
    failures: FailureSettings
    stocking: StockingSettings


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    raw = yaml.safe_load(SETTINGS_PATH.read_text())
    c = raw["confidence"]
    e = raw["expiring_lots"]
    f = raw["failures"]
    s = raw["stocking"]
    return Settings(
        confidence=ConfidenceSettings(
            base=float(c["base"]),
            days_weight=float(c["days_weight"]),
            days_horizon=float(c["days_horizon"]),
            moves_weight=float(c["moves_weight"]),
            moves_cap=float(c["moves_cap"]),
            discrepancy_weight=float(c["discrepancy_weight"]),
            verification_threshold=float(c["verification_threshold"]),
            discrepancy_bump=float(c["discrepancy_bump"]),
            confidence_score_weight=float(c["confidence_score_weight"]),
        ),
        expiring_lots=ExpiringLotSettings(
            window_days=int(e["window_days"]),
            scan_schedule=str(e["scan_schedule"]),
        ),
        failures=FailureSettings(
            verify_time_buffer_minutes=int(f["verify_time_buffer_minutes"]),
        ),
        stocking=StockingSettings(
            min_failures_to_suggest=int(s["min_failures_to_suggest"]),
        ),
    )
