import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type {
  Candidate,
  DashboardStats,
  ExpiringPart,
  FieldSpec,
  Flight,
  OverrideReason,
  Plan,
  PlanEvent,
  ShipmentDraft,
  Station,
} from "../api";
import { StationMap } from "../components/StationMap";
import { ExpiryQueue } from "../components/ExpiryQueue";
import { PlanCard } from "../components/PlanCard";
import { EventTimeline } from "../components/EventTimeline";
import { ShipmentDraftPanel } from "../components/ShipmentDraftPanel";
import { VerifyTasksPanel } from "../components/VerifyTasksPanel";
import { ExpiringLotsPanel } from "../components/ExpiringLotsPanel";
import { FailuresPanel } from "../components/FailuresPanel";
import { StockingPanel } from "../components/StockingPanel";
import { DashboardStatsBar } from "../components/DashboardStatsBar";

export function Dashboard() {
  const [stations, setStations] = useState<Station[]>([]);
  const [parts, setParts] = useState<ExpiringPart[]>([]);
  const [flights, setFlights] = useState<Flight[]>([]);
  const [fieldSpecs, setFieldSpecs] = useState<FieldSpec[]>([]);
  const [stats, setStats] = useState<DashboardStats | null>(null);

  const [selectedPart, setSelectedPart] = useState<ExpiringPart | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [loadingCandidates, setLoadingCandidates] = useState(false);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [events, setEvents] = useState<PlanEvent[]>([]);
  const [drafts, setDrafts] = useState<ShipmentDraft[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [verifyRefreshKey, setVerifyRefreshKey] = useState(0);
  const bumpVerifyRefresh = () => setVerifyRefreshKey((k) => k + 1);

  const refreshStats = () => {
    api.getDashboardStats().then(setStats).catch((e) => setError(String(e)));
  };

  useEffect(() => {
    api.getStations().then(setStations).catch((e) => setError(String(e)));
    api.getExpiringParts().then(setParts).catch((e) => setError(String(e)));
    api.getFlights().then(setFlights).catch((e) => setError(String(e)));
    api.getFieldSpecs().then(setFieldSpecs).catch((e) => setError(String(e)));
    refreshStats();
  }, []);

  const refreshCandidates = (serial: string) => {
    setLoadingCandidates(true);
    api
      .getCandidates(serial)
      .then(setCandidates)
      .catch((e) => setError(String(e)))
      .finally(() => setLoadingCandidates(false));
  };

  useEffect(() => {
    if (!selectedPart) {
      setCandidates([]);
      setPlan(null);
      setEvents([]);
      setDrafts([]);
      return;
    }
    setPlan(null);
    setEvents([]);
    setDrafts([]);
    refreshCandidates(selectedPart.serial);
  }, [selectedPart]);

  useEffect(() => {
    if (!plan) {
      setEvents([]);
      return;
    }
    api.getEvents(plan.id).then(setEvents).catch((e) => setError(String(e)));
  }, [plan?.id, plan?.status, plan?.reason, plan?.pending_option]);

  useEffect(() => {
    if (!plan) {
      setDrafts([]);
      return;
    }
    api.getShipments(plan.id).then(setDrafts).catch((e) => setError(String(e)));
  }, [plan?.id, plan?.status]);

  const handleSelectPart = (part: ExpiringPart) => {
    setError(null);
    setSelectedPart(part);
  };

  const handleApproveTop = async () => {
    if (!selectedPart) return;
    setError(null);
    try {
      const created = await api.createPlan(selectedPart.serial);
      const approved = await api.approvePlan(created.id);
      setPlan(approved);
      bumpVerifyRefresh();
    } catch (e) {
      setError(String(e));
    }
  };

  const handleChooseAlternative = async (candidate: Candidate, reason: OverrideReason, note: string) => {
    if (!selectedPart) return;
    setError(null);
    try {
      let planId = plan?.id;
      if (!planId) {
        const created = await api.createPlan(selectedPart.serial);
        planId = created.id;
      }
      const result = await api.chooseAlternative(planId, {
        option: candidate.option,
        source: candidate.source,
        flight_number: candidate.flight_number,
        reason,
        note: note.trim() || undefined,
      });
      setPlan(result);
      bumpVerifyRefresh();
    } catch (e) {
      setError(String(e));
    }
  };

  const handleApprovePending = async () => {
    if (!plan) return;
    setError(null);
    try {
      const result = await api.approvePlan(plan.id);
      setPlan(result);
      bumpVerifyRefresh();
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
      if (selectedPart) refreshCandidates(selectedPart.serial);
    } catch (e) {
      setError(String(e));
    }
  };

  const handleSubmitShipment = async (draftId: number) => {
    setError(null);
    try {
      const result = await api.submitShipment(draftId);
      setPlan(result.plan);
      setDrafts((prev) => prev.map((d) => (d.id === result.draft.id ? result.draft : d)));
    } catch (e) {
      setError(String(e));
    }
  };

  const handleVerifyTaskResolved = () => {
    refreshStats();
    if (plan) {
      api.getPlan(plan.id).then(setPlan).catch((e) => setError(String(e)));
    }
  };

  const activeStatuses: Plan["status"][] = ["proposed", "approved", "at_risk", "re_routed"];
  const canDelay = !!plan && !!plan.flight_number && activeStatuses.includes(plan.status);

  return (
    <div className="app">
      <header className="app-header">
        <h1>COMAT Copilot</h1>
        <span className="tagline">finding every part about to expire, and the cheapest safe way to fix it</span>
        <nav className="app-nav">
          <Link to="/pickslip">PickSlip</Link>
          <Link to="/issued">Issued Summary</Link>
        </nav>
      </header>
      <DashboardStatsBar stats={stats} />
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
          onApproveTop={handleApproveTop}
          onChooseAlternative={handleChooseAlternative}
          onApprovePending={handleApprovePending}
          onSimulateDelay={handleSimulateDelay}
          error={error}
        />
        <ShipmentDraftPanel drafts={drafts} fieldSpecs={fieldSpecs} onSubmit={handleSubmitShipment} error={null} />
      </div>
      <div className="stores-queue">
        <VerifyTasksPanel onResolved={handleVerifyTaskResolved} refreshSignal={verifyRefreshKey} />
        <ExpiringLotsPanel onApproved={refreshStats} />
        <FailuresPanel onReported={refreshStats} />
        <StockingPanel onApproved={refreshStats} />
      </div>
      <EventTimeline events={events} />
    </div>
  );
}
