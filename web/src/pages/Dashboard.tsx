import { useEffect, useState } from "react";
import { api } from "../api";
import type { Candidate, ExpiringPart, Flight, Plan, PlanEvent, Station } from "../api";
import { StationMap } from "../components/StationMap";
import { ExpiryQueue } from "../components/ExpiryQueue";
import { PlanCard } from "../components/PlanCard";
import { EventTimeline } from "../components/EventTimeline";

export function Dashboard() {
  const [stations, setStations] = useState<Station[]>([]);
  const [parts, setParts] = useState<ExpiringPart[]>([]);
  const [flights, setFlights] = useState<Flight[]>([]);

  const [selectedPart, setSelectedPart] = useState<ExpiringPart | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [loadingCandidates, setLoadingCandidates] = useState(false);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [events, setEvents] = useState<PlanEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getStations().then(setStations).catch((e) => setError(String(e)));
    api.getExpiringParts().then(setParts).catch((e) => setError(String(e)));
    api.getFlights().then(setFlights).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!selectedPart) {
      setCandidates([]);
      setPlan(null);
      setEvents([]);
      return;
    }
    setLoadingCandidates(true);
    setPlan(null);
    setEvents([]);
    api
      .getCandidates(selectedPart.serial)
      .then(setCandidates)
      .catch((e) => setError(String(e)))
      .finally(() => setLoadingCandidates(false));
  }, [selectedPart]);

  useEffect(() => {
    if (!plan) {
      setEvents([]);
      return;
    }
    api.getEvents(plan.id).then(setEvents).catch((e) => setError(String(e)));
  }, [plan?.id, plan?.status, plan?.reason]);

  const handleSelectPart = (part: ExpiringPart) => {
    setError(null);
    setSelectedPart(part);
  };

  const handleProposeAndApprove = async () => {
    if (!selectedPart) return;
    setError(null);
    try {
      const created = await api.createPlan(selectedPart.serial);
      const approved = await api.approvePlan(created.id);
      setPlan(approved);
    } catch (e) {
      setError(String(e));
    }
  };

  const handleSimulateDelay = async (minutes: number) => {
    if (!plan || !plan.flight_number) return;
    setError(null);
    try {
      const flight = flights.find((f) => f.flight_number === plan.flight_number);
      if (!flight) {
        setError(`Could not find flight ${plan.flight_number}`);
        return;
      }
      const result = await api.delayFlight(flight.id, minutes);
      const updated = result.replanned_plans.find((p) => p.id === plan.id);
      if (updated) setPlan(updated);
      api.getFlights().then(setFlights);
    } catch (e) {
      setError(String(e));
    }
  };

  const activeStatuses: Plan["status"][] = ["proposed", "approved", "at_risk", "re_routed"];
  const canDelay = !!plan && !!plan.flight_number && activeStatuses.includes(plan.status);

  return (
    <div className="app">
      <header className="app-header">
        <h1>COMAT Copilot</h1>
        <span className="tagline">finding every part about to expire, and the cheapest safe way to fix it</span>
      </header>
      <div className="app-main">
        <ExpiryQueue parts={parts} selectedSerial={selectedPart?.serial ?? null} onSelect={handleSelectPart} />
        <div className="map-panel">
          <StationMap stations={stations} sourceCode={plan?.source ?? null} destCode={selectedPart?.station ?? null} />
        </div>
        <PlanCard
          part={selectedPart}
          candidates={candidates}
          loadingCandidates={loadingCandidates}
          plan={plan}
          canDelay={canDelay}
          onProposeAndApprove={handleProposeAndApprove}
          onSimulateDelay={handleSimulateDelay}
          error={error}
        />
      </div>
      <EventTimeline events={events} />
    </div>
  );
}
