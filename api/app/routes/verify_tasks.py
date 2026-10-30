from datetime import datetime
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from sqlmodel import select

from app.db import get_session
from app.models import InventoryItem, Plan, VerifyTask, VerifyTaskStatus
from app.planner.verification import VerifyTaskAlreadyResolved, resolve_verify_task

router = APIRouter(prefix="/verify-tasks", tags=["verify-tasks"])


@router.get("", response_model=list[VerifyTask])
def list_verify_tasks(status: Optional[VerifyTaskStatus] = None):
    with get_session() as session:
        query = select(VerifyTask).order_by(VerifyTask.created_at)
        if status is not None:
            query = query.where(VerifyTask.status == status)
        return session.exec(query).all()


@router.get("/{task_id}", response_model=VerifyTask)
def get_verify_task(task_id: int):
    with get_session() as session:
        task = session.get(VerifyTask, task_id)
        if not task:
            raise HTTPException(404, f"verify task {task_id} not found")
        return task


@router.post("/{task_id}/photo")
def submit_photo(task_id: int, photo: UploadFile = File(...), verified_by: str = Form("Stores")):
    with get_session() as session:
        task = session.get(VerifyTask, task_id)
        if not task:
            raise HTTPException(404, f"verify task {task_id} not found")

        try:
            resolved = resolve_verify_task(session, task, photo.filename or "", datetime.now(), verified_by)
        except VerifyTaskAlreadyResolved as e:
            raise HTTPException(409, str(e))

        item = session.get(InventoryItem, resolved.inventory_serial)
        plan = session.get(Plan, resolved.plan_id)
        return {"task": resolved, "inventory_item": item, "plan": plan}
