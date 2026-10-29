# COMAT Copilot

COMAT Copilot keeps aircraft off the ground by finding every part about to expire and planning the cheapest safe replacement before it becomes an AOG (aircraft-on-ground). It watches inventory by station, knows where each tail number overnights, and decides whether to fly a spare in as COMAT, pull it from a nearby station, or buy it — and re-plans automatically when a flight it's counting on changes.

Built for the Supplier Relationship Management track at [hackfw](https://hackfw.devpost.com). Full build spec and demo script: [docs/spec.md](docs/spec.md).

## Demo

1. Open the dashboard: a map of stations and an expiring-parts queue sorted by days left.
2. Click a part (try the one on tail **N501EV** at **CVG**) to see three ranked options side by side, with cost, arrival time, and risk.
3. **Propose & Approve** the recommendation — COMAT on the DFW→CVG flight — and watch the event timeline log it.
4. Hit **Simulate Delay** on that flight. The plan recalculates and, if the delay is big enough, re-routes to the ground transfer or a vendor buy, with the switch logged as a new event.

## Quick start

### Docker (recommended — one command)

```bash
cp .env.example .env   # optional: add ANTHROPIC_API_KEY for Claude-written reason lines
docker compose up --build
```

Dashboard: http://localhost:5173 · API docs: http://localhost:8000/docs

Without an `ANTHROPIC_API_KEY`, plan reasons fall back to a plain templated line (e.g. *"ride flight EV2301 from DFW, arrives 20:25"*) instead of Claude's write-up — everything else works the same either way.

### Manual setup — macOS/Linux

```bash
# Terminal 1: API
cd api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m seed.generate
pytest tests/ -v
uvicorn app.main:app --reload
```

```bash
# Terminal 2: dashboard
cd web
npm install
npm run dev
```

### Manual setup — Windows (PowerShell)

```powershell
# Terminal 1: API
cd api
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m seed.generate
pytest tests/ -v
uvicorn app.main:app --reload
```

```powershell
# Terminal 2: dashboard
cd web
npm install
npm run dev
```

Either way, open http://localhost:5173.

## Architecture

[**Architecture diagram**](docs/architecture-diagram.html) -- three source systems on the left (Sceptre, iCargo, a shipping system), COMAT Copilot's adapter layer in the middle, the planner on the right. Today all three adapters answer from seeded mock data; in a pilot each one swaps independently (`PARTS_ADAPTER`, `CARGO_ADAPTER`, `SHIPPING_ADAPTER`) and nothing else in the app changes.

```
comat-copilot/
  docker-compose.yml     # one command: api + web, seeded data
  .env.example           # ANTHROPIC_API_KEY, DATABASE_URL, EXPIRY_WINDOW_DAYS
  docs/
    architecture-diagram.html  # the three-adapters picture above, standalone
  api/
    app/
      main.py             # FastAPI app, CORS, router wiring
      models.py           # the 9 SQLModel tables (8 from the data model + plan_event)
      db.py                # engine/session, reads DATABASE_URL (SQLite by default)
      schemas.py           # request/response shapes that aren't tables
      planner/
        candidates.py     # finds COMAT / transfer / buy options, flags disqualified ones with why
        score.py          # cost + risk scoring (+ STD bump risk), ranking
        priority_rules.py # priority/commodity-profile/handoff-route rules
        flight_search.py  # direct + hub-connection flight search, booking cutoffs
        decisions.py      # approve / choose-alternative -- the human-decision paths
        replan.py         # reruns active plans when a flight changes
      adapters/            # the pilot swap points -- mock today, a real system behind each later
        sceptre_adapter.py    # parts & expiry (PARTS_ADAPTER)
        icargo_adapter.py     # cargo capacity & booking (CARGO_ADAPTER)
        safe_adapter.py       # SAFE-ready shipment draft (safe_fields.yaml)
      ai/
        explain.py        # Claude writes the one-line reason; templated fallback with no key
      routes/              # parts, plans, flights, events, stations
    seed/
      fleet.json           # the static, human-reviewable world: stations, tails, parts, vendors
      generate.py          # layers on time-relative state; hero scenario + decoys hardcoded
    tests/                 # pytest: planner, re-plan, adapters, Claude fallback
  web/
    src/
      api.ts               # typed fetch client
      pages/Dashboard.tsx
      components/          # StationMap, ExpiryQueue, PlanCard, EventTimeline
```

**Decision engine:** for each expiring part, the planner builds every COMAT/transfer/buy option, drops anything that can't arrive before the deadline or relies on an unserviceable spare, and ranks what's left by `score = cost + w × P(miss deadline) × AOG cost`. A flight delay triggers `POST /flights/{id}/delay`, which reruns every plan riding on that flight and logs the outcome as a `plan_event`.

**Data:** SQLite by default (zero setup); set `DATABASE_URL` to a Postgres URL for a real deployment. The seed script rebuilds the database from scratch every time it runs, so the demo state is always deterministic.

## Testing

```bash
cd api
pytest tests/ -v
```

14 tests cover the hero scenario and both decoys (unserviceable spare, too-slow vendor quote), re-planning on a flight delay, and the Claude reason-line fallback.
