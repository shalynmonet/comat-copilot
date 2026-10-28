from datetime import timedelta

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.db import get_session
from app.models import Flight, FlightStatus
from app.planner.replan import replan_for_flight
from app.schemas import DelayRequest

router = APIRouter(prefix="/flights", tags=["flights"])


@router.get("", response_model=list[Flight])
def list_flights():
    with get_session() as session:
        return session.exec(select(Flight)).all()


@router.get("/{flight_id}", response_model=Flight)
def get_flight(flight_id: int):
    with get_session() as session:
        flight = session.get(Flight, flight_id)
        if not flight:
            raise HTTPException(404, f"flight {flight_id} not found")
        return flight


@router.post("/{flight_id}/delay")
def simulate_delay(flight_id: int, body: DelayRequest = DelayRequest()):
    with get_session() as session:
        flight = session.get(Flight, flight_id)
        if not flight:
            raise HTTPException(404, f"flight {flight_id} not found")

        flight.status = FlightStatus.delayed
        flight.sched_dep = flight.sched_dep + timedelta(minutes=body.minutes)
        flight.sched_arr = flight.sched_arr + timedelta(minutes=body.minutes)
        session.add(flight)
        session.commit()
        session.refresh(flight)

        replanned = replan_for_flight(session, flight)
        session.refresh(flight)  # replan's own commit() re-expired it
        return {"flight": flight, "replanned_plans": replanned}
