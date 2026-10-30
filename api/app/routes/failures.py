from fastapi import APIRouter, HTTPException

from app.db import get_session
from app.planner.failures import NoInstalledPartForFailure, report_failure
from app.schemas import FailureReportCreate

router = APIRouter(prefix="/failures", tags=["failures"])


@router.post("")
def create_failure_report(body: FailureReportCreate):
    with get_session() as session:
        try:
            request, plan = report_failure(
                session, body.tail_number, body.station, body.part_number, body.reported_by, body.notes
            )
        except NoInstalledPartForFailure as e:
            raise HTTPException(404, str(e))
        return {"request": request, "plan": plan}
