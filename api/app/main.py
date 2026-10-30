from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.routes import (
    admin,
    events,
    expiring_lots,
    failures,
    flights,
    inventory,
    part_requests,
    parts,
    plans,
    requests,
    shipments,
    stations,
    stats,
    stocking,
    verify_tasks,
)

app = FastAPI(title="COMAT Copilot API")

# Made-up demo tag photos (see seed/tag_images.py) -- lets the UI offer
# "use the seeded sample photo" for the low-confidence verify flow
# without the user needing to find the files on disk themselves.
DEMO_ASSETS_DIR = Path(__file__).resolve().parent.parent / "seed" / "assets"
if DEMO_ASSETS_DIR.exists():
    app.mount("/demo-assets", StaticFiles(directory=DEMO_ASSETS_DIR), name="demo-assets")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


app.include_router(parts.router)
app.include_router(plans.router)
app.include_router(flights.router)
app.include_router(events.router)
app.include_router(stations.router)
app.include_router(shipments.router)
app.include_router(requests.router)
app.include_router(verify_tasks.router)
app.include_router(inventory.router)
app.include_router(part_requests.router)
app.include_router(expiring_lots.router)
app.include_router(failures.router)
app.include_router(stocking.router)
app.include_router(stats.router)
app.include_router(admin.router)


@app.get("/")
def health():
    return {"status": "ok"}
