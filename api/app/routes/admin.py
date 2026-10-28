"""A protected endpoint that re-runs the seed script in place, so a public,
always-on deployment's demo flight (fixed in calendar time) doesn't go stale
hours after the container last started. Guarded by a shared secret rather
than left open, since it wipes and rebuilds the database.

Only safe because the service is capped at a single instance (see the
Cloud Run deploy flags) -- with more than one instance, each would have its
own local SQLite file and this would only reseed whichever one handled the
request.
"""

import os

from fastapi import APIRouter, Header, HTTPException

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/reseed")
def reseed(x_reseed_secret: str = Header(default="")):
    expected = os.environ.get("RESEED_SECRET")
    if not expected or x_reseed_secret != expected:
        raise HTTPException(403, "invalid or missing reseed secret")

    from seed.generate import main as run_seed

    run_seed()
    return {"status": "reseeded"}
