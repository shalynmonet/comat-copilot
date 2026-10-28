from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import init_db
from app.routes import admin, events, flights, parts, plans, stations

app = FastAPI(title="COMAT Copilot API")

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
app.include_router(admin.router)


@app.get("/")
def health():
    return {"status": "ok"}
