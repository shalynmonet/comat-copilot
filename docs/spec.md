# COMAT Copilot: Build Spec

Oct 28, 2026 · @shalyn

## Overview

COMAT Copilot keeps aircraft off the ground by finding every part about to expire and planning the cheapest safe replacement before it becomes an AOG. It watches inventory by station, knows where each tail number overnights, and decides whether to fly a spare in as COMAT, pull it from a nearby station, or buy it.

- **Track:** Supplier Relationship Management (parts, stations, vendors and live order state as one graph). Open Forum is the fallback if organizers confirm it counts.
- **Operator:** maintenance control and material logistics planners at a regional carrier.
- **Demo story:** a part on a plane overnighting in Kentucky expires in 2 days, the spare is in Dallas, and the Copilot books it on tonight's flight. Then the flight gets delayed live and the plan re-routes on screen.
- **Open question:** final submission deadline and Demo Day date (brief says more details to come).

## Data model

Eight tables carry the whole loop: four describe the world (fleet, stations, parts, vendors), two hold live state (inventory, flights), and two record what the Copilot decided and did.

| Table | Key fields | Links to |
| --- | --- | --- |
| `station` | code (DFW, CVG), name, lat/lon, has\_maintenance, stores\_capacity | inventory\_item, flight |
| `aircraft` | tail\_number, type (E175, CRJ900), current\_station, overnight\_station | installed\_part, flight |
| `part` | part\_number, description, shelf\_life\_days, is\_rotable, unit\_cost, weight\_lb | inventory\_item, installed\_part, vendor\_quote |
| `installed_part` | serial, part\_number, tail\_number, position, installed\_on, expires\_on, hours\_remaining | aircraft, part |
| `inventory_item` | serial, part\_number, station, condition (serviceable / unserviceable / quarantined), expires\_on, last\_counted\_on | station, part |
| `flight` | flight\_number, tail\_number, origin, dest, sched\_dep, sched\_arr, status, cargo\_capacity\_lb | aircraft, station |
| `vendor_quote` | vendor, part\_number, price, lead\_time\_hrs, ship\_to\_station, certs (FAA 8130-3) | part |
| `plan` | id, installed\_serial, option (COMAT / transfer / buy), source, flight\_number, cost, risk\_score, status, reason | installed\_part, flight, inventory\_item |

- **Expiry window:** an `installed_part` enters the queue when `expires_on` falls within the next N days (default 7).
- **Inventory checks:** each count writes a new `inventory_item` snapshot so the system has numbers to compare against and keeps history.
- **Event log:** every plan change (created, re-routed, approved, shipped, installed) appends to a `plan_event` table, which becomes the auditable timeline for the demo.

## Decision engine

&#91;embedded content: decision loop · 5 steps, 1 re-plan trigger\]

For each expiring part the planner builds every option, drops any that can't arrive before the deadline or use an unserviceable spare, and ranks the rest by a single score.

```latex
\text{score} = \text{cost} + w \times P(\text{miss deadline}) \times \text{AOG cost}
```

- **COMAT:** near-zero cost; risk rises as the flight's slack before the deadline shrinks.
- **Transfer:** pull a serviceable spare from another station, then route it on a COMAT flight.
- **Buy:** vendor price plus expedite; risk from lead time.
- **Re-plan:** when a booked flight changes status, every plan riding on it reruns, and the new pick is logged as a plan event.

## Repo structure and stack

One repo, two services, one command to boot: `docker compose up` brings up the API and dashboard with seeded data, which is what the "clone, run, maintain" rule asks for.

| Layer | Choice | Why |
| --- | --- | --- |
| API | Python, FastAPI, SQLModel | Fast to build, typed models double as API docs at /docs |
| Database | SQLite for the demo, Postgres via env var | Zero setup for judges, real DB path for a pilot |
| Planner | Plain Python scoring, no solver | Explainable, easy to test, fast enough for a regional fleet |
| AI layer | Claude API | Writes the plain-English reason on each plan and parses free-text inventory notes |
| Dashboard | React, Vite, Leaflet map | Stations on a map, expiring parts queue, plan cards |
| Packaging | Docker Compose, plus PowerShell steps in the README | Boots on any machine, including Windows |

```
comat-copilot/
  README.md            # problem, demo GIF, quick start, architecture
  docker-compose.yml
  .env.example         # ANTHROPIC_API_KEY, DATABASE_URL, EXPIRY_WINDOW_DAYS
  api/
    app/
      main.py          # FastAPI app and routes
      models.py        # tables from the data model
      planner/
        candidates.py  # find COMAT, transfer and buy options
        score.py       # cost and risk scoring
        replan.py      # re-run plans hit by a schedule change
      ai/
        explain.py     # Claude writes the reason line
      routes/          # parts, plans, flights, events
    seed/
      generate.py      # builds the synthetic fleet
      fleet.json
    tests/
      test_planner.py
  web/
    src/
      pages/Dashboard.tsx
      components/      # StationMap, ExpiryQueue, PlanCard, EventTimeline
  docs/
    architecture.md
    demo-script.md
```

## Synthetic demo data and demo script

A seeded regional fleet keeps the demo realistic without any airline data: 20 tails, 8 stations, one day of flights, and about 40 parts with expiry dates spread so 5 to 6 land in the 7-day window.

- **Stations:** DFW (main stores and hub), ORD, CVG, MEM, AUS, TUL, OKC, SDF. DFW and ORD have full maintenance; the rest are line stations.
- **Hero scenario:** tail N501EV overnights at CVG with a part expiring in 2 days. The serviceable spare sits at DFW, and DFW to CVG flies at 6:40 pm.
- **Decoys:** one spare at ORD that is unserviceable, and one vendor quote that is cheaper but arrives after the deadline, so the Copilot visibly rejects both.
- **Sanity check:** have your boyfriend review station list, part types and timing so a judge with airline experience doesn't spot anything off.

**Demo script (about 3 minutes)**

1. Open the dashboard: map of stations, expiring parts queue sorted by days left.
2. Click the CVG part. Show three options side by side with cost, arrival time and risk.
3. Copilot recommends COMAT on the DFW to CVG flight, with a one-line reason. Approve it; a work order and shipping ticket generate.
4. Hit "Simulate delay" on that flight. The plan flips to at-risk and re-routes to the next viable flight or a transfer, with the event logged.
5. Close on the event timeline: every decision traceable, with a human approval on each one.

## Build plan and submission checklist

Build the thin path end to end first, then polish. A working loop with a plain UI beats a beautiful dashboard with no re-plan.

**Build order**

- [ ] Models and seed script, with the hero scenario baked in
- [ ] Planner: candidates and scoring, plus tests for the hero case and both decoys
- [ ] API routes for parts, plans, flights and events
- [ ] Re-plan on flight delay, triggered by a "Simulate delay" endpoint
- [ ] Claude reason lines on each plan
- [ ] Dashboard: queue, plan cards, map, event timeline
- [ ] Docker Compose and README quick start, tested on a clean clone

**Submission**

- [ ] Register at hackfw.devpost.com
- [ ] Register in the Fort Worth talent database (talent.fwtx.city)
- [ ] Public GitHub repo (github.com/shalynmonet)
- [ ] Video demo of the full loop, including the live delay
- [ ] Track named: Supplier Relationship Management
- [ ] RSVP for in-person Demo Day (luma.com/ygyxb4yy)
