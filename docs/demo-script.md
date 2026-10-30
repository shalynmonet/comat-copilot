# Demo Script: step-by-step click-through

Companion to [spec.md](spec.md). Matches the seeded state produced by `python -m seed.generate`
(see `api/seed/generate.py` for the exact scenario constants) — reseed before each run so the
data is always in this state.

## Setup

```bash
cp .env.example .env   # optional: ANTHROPIC_API_KEY for Claude-written reason lines
docker compose up --build
```

Open the dashboard: http://localhost:5173

---

## Act 0 — Orient on the dashboard

1. Point out the **stats strip** at the top (AOGs avoided, plane-side runs avoided, phantom
   parts caught, picks verified by photo, discrepancies caught at pick, shelf-life value
   saved, failure response time, station discrepancy rates). These all start near zero/empty —
   they fill in as you work through the acts below.
2. Point out the **map** (stations, blue = has a maintenance base) and the **Expiring Parts**
   queue on the left, sorted by days left, most urgent (red "Xd" badge) on top.

## Act 1 — Hero scenario: COMAT in to save an AOG

1. In **Expiring Parts**, click **Crew Oxygen Bottle, 2L** — tail **N501EV** at **CVG**, 2 days
   out.
2. The **Plan** panel shows three ranked candidates:
   - **★ COMAT** from **DFW** on flight **EV2301** — the top pick, near-zero cost.
   - A disqualified candidate from the **ORD** unserviceable spare ("Disqualified: ...
     unserviceable").
   - A disqualified vendor quote from **SkyParts Direct** — cheaper, but arrives after the
     deadline.
3. Note the map now draws a red dashed line **DFW → CVG**.
4. Click **Approve** on the top candidate. The plan turns **approved**, the reason line appears
   (Claude-written if `ANTHROPIC_API_KEY` is set, otherwise a templated line), and the **SAFE
   Shipment Draft** panel on the right fills in with the AWB, weight, DG flag, etc.
5. Scroll to the **Event Timeline** at the bottom — the `created` and `approved` events are
   logged with timestamps.
6. Optional: click **Copy to SAFE** or **Export CSV** on the shipment draft to show the
   hand-off out of the app.

## Act 2 — Live re-plan on a flight delay

1. With the Act 1 plan still open, find the **Simulate Delay** control in the plan summary
   (minutes input next to "min delay on EV2301").
2. Enter a large delay (e.g. **500**) and click **Simulate Delay**.
3. The plan flips to **at risk** ("a booked flight changed"). If a feasible alternative exists,
   a **pending recommendation** appears — click **Approve New Recommendation** to re-route.
   If none exists, the banner says so explicitly.
4. Back in the Event Timeline, a new `re_routed` (or `at_risk`) event is now logged — the whole
   decision trail stays auditable.

## Act 3 — Dangerous goods disqualification

1. Still on the hero part's candidate list (Act 1), point out the **⚠ Dangerous goods** badge
   on the oxygen bottle candidates.
2. Explain the seeded DG decoy: a second serviceable **ORD** spare of the same part exists, but
   it's reachable only by tail **N516EV**'s flight — the one flight in the fleet seeded with
   `accepts_dg = false`. It shows up as "feasible-looking" but gets disqualified specifically
   for not accepting DG cargo, right next to the real DFW spare that does.

## Act 4 — Low-confidence spare → photo verification → phantom catch

1. In **Expiring Parts**, the DG-decoy spare at ORD is also seeded low-confidence (never
   photo-verified, moved 5 times in 30 days, station discrepancy rate 35%). If you choose it as
   an override on any plan (via **Choose this instead**), its confidence badge shows under
   60% with a reason.
2. Scroll down to **Verify Tasks** in the Stores Queue strip. Any plan resting on a
   low-confidence spare raises a task here.
3. Click **Use sample (match)** — the extracted tag data matches the record, status turns
   **matched**, confidence is raised, plan continues.
4. Click **Use sample (mismatch)** on another task — the extracted part number/serial/condition
   don't match the record, it's flagged as a **phantom part**, and the plan automatically
   re-routes to the next source. This is what drives the "Phantom parts caught" and "Picks
   verified by photo" stats at the top.

## Act 5 — Hub-connection routing

1. Click **Hydraulic Pump, Electric** — tail **N501EV**, 3 days out. Its only spare lives at
   **TUL**, which has no direct flight to CVG.
2. The top candidate routes **TUL → DFW → CVG**: tail **N511EV**'s flight **EV2250** (TUL→DFW,
   lands well before EV2301 departs) connecting onto the hero's own EV2301 leg into CVG. Call
   out that the planner found a two-leg hub connection automatically, not just direct flights.

## Act 6 — Oversize part forces cargo routing

1. Click **Main Landing Gear Tire** — tail **N513EV** at **OKC**, 1 day out, and flagged
   oversize.
2. Because it's both short-fused and oversize, the recommended option routes as cargo on the
   aircraft's own repositioning flight rather than planeside stowage — point out the
   oversize/DG badges and the detail line explaining the routing choice.

## Act 7 — Already-AOG, raised by maintenance control

1. Click **APU Starter Battery** — tail **N502EV** at **ORD**, shown with a negative days-left
   badge (already past expiry). This one was raised directly as a shipping request by
   maintenance control, not by Copilot's own scan — the kind of reactive firefighting the
   early-warning queue exists to prevent more of.
2. Open **Report Failure** → **Shipping Requests** list (bottom strip) to show it sitting there
   with an **AOG** priority badge.

## Act 8 — Stores Queue: Expiring Lots

1. Scroll to **Expiring Lots** in the bottom strip.
2. **Move**: a `FAK-STD` lot at ORD that CVG genuinely needs before it expires — click
   **Approve** to move it.
3. **Replace**: a `PBE-SMOKE` lot at SDF with no demand anywhere and no other spare at its own
   station — approving it raises a replacement request instead, shown in **Shipping
   Requests**.

## Act 9 — Report a failure live

1. In **Report Failure**, fill in:
   - Tail number: **N508EV**
   - Station: **AUS**
   - Part number: **AVIONICS-GPS**
   - Reported by: **Maintenance Control**
2. Submit. The closest spare (ORD) is low-confidence; the real answer is the already-verified
   spare at **DFW** — the result banner shows whether a plan was found and from where.
3. Point out **Stocking Suggestions** in the same strip: enough AVIONICS-GPS/CRJ900 failures in
   the seeded removal history (three in the last ~85 days) cross the stocking threshold, so
   Copilot proactively suggests stocking a spare at the station that keeps seeing the failures
   — click **Approve** to action it.

## Act 10 — PickSlip and Issued Summary (mobile/stores view)

1. Click **PickSlip** in the header nav (or go straight to http://localhost:5173/pickslip —
   it's a single-column, phone-friendly page).
2. Find the open request for **STARTER-GEN**, tail **N509EV**, mechanic "Mike (Line Maint)",
   expected at **BIN-AUS-07**. Click **Pick this**.
3. Click **Sample: match** to issue it cleanly, or **Sample: mismatch** to show the shelf tag
   not matching M3's record — it gets flagged with a suggested next source instead of issued.
4. Click **← Dashboard**, then open **Issued Summary** to see the two tables this produces:
   parts issued (with photo-verified column) and flagged discrepancies (with reason and
   suggested next step).

---

## Closing

Back on the dashboard, point at the stats strip one more time — AOGs avoided, phantom parts
caught, picks verified by photo, and shelf-life value saved should all be non-zero now, each
one traceable back to a specific decision in the Event Timeline.
