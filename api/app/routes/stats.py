from fastapi import APIRouter
from sqlmodel import select

from app.db import get_session
from app.models import (
    ExpiringLotAction,
    ExpiringLotActionStatus,
    ExpiringLotActionType,
    PartRequest,
    PartRequestStatus,
    Station,
    VerifyTask,
    VerifyTaskStatus,
)
from app.planner.failures import compute_failure_response_time_median_minutes
from app.planner.intake import compute_avoided_stats
from app.schemas import DashboardStatsOut, StationDiscrepancyOut

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("", response_model=DashboardStatsOut)
def get_dashboard_stats():
    with get_session() as session:
        avoided = compute_avoided_stats(session)
        phantom_parts_caught = len(
            session.exec(select(VerifyTask).where(VerifyTask.status == VerifyTaskStatus.mismatched)).all()
        )
        picks_verified_by_photo = len(
            session.exec(select(PartRequest).where(PartRequest.status == PartRequestStatus.issued)).all()
        )
        discrepancies_caught_at_pick = len(
            session.exec(select(PartRequest).where(PartRequest.status == PartRequestStatus.flagged)).all()
        )
        saved_actions = session.exec(
            select(ExpiringLotAction).where(
                ExpiringLotAction.status == ExpiringLotActionStatus.approved,
                ExpiringLotAction.action.in_([ExpiringLotActionType.use, ExpiringLotActionType.move]),
            )
        ).all()
        shelf_life_value_saved = sum(a.unit_cost for a in saved_actions)
        stations = session.exec(select(Station)).all()
        failure_response_time_median_minutes = compute_failure_response_time_median_minutes(session)

        return DashboardStatsOut(
            aogs_avoided=avoided.aogs_avoided,
            planeside_runs_avoided=avoided.planeside_runs_avoided,
            phantom_parts_caught=phantom_parts_caught,
            station_discrepancy_rates=[
                StationDiscrepancyOut(station=s.code, discrepancy_rate=s.discrepancy_rate) for s in stations
            ],
            picks_verified_by_photo=picks_verified_by_photo,
            discrepancies_caught_at_pick=discrepancies_caught_at_pick,
            shelf_life_value_saved=shelf_life_value_saved,
            failure_response_time_median_minutes=failure_response_time_median_minutes,
        )
