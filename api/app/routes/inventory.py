from fastapi import APIRouter, HTTPException

from app.db import get_session
from app.models import InventoryItem

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/{serial}", response_model=InventoryItem)
def get_inventory_item(serial: str):
    with get_session() as session:
        item = session.get(InventoryItem, serial)
        if not item:
            raise HTTPException(404, f"inventory item {serial} not found")
        return item
