import { useState } from "react";
import type { Candidate, ExpiringPart, Plan } from "../api";

interface Props {
  part: ExpiringPart | null;
  candidates: Candidate[];
  loadingCandidates: boolean;
  plan: Plan | null;
  canDelay: boolean;
  onProposeAndApprove: () => Promise<void>;
  onSimulateDelay: (minutes: number) => Promise<void>;
  error: string | null;
}

function formatEta(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function PlanCard({
  part,
  candidates,
  loadingCandidates,
  plan,
  canDelay,
  onProposeAndApprove,
  onSimulateDelay,
  error,
}: Props) {
  const [minutes, setMinutes] = useState(600);
  const [busy, setBusy] = useState(false);

  if (!part) {
    return (
      <div className="panel">
        <h2>Plan</h2>
        <p className="empty-hint">Select an expiring part from the queue to see its options.</p>
      </div>
    );
  }

  const handlePropose = async () => {
    setBusy(true);
    try {
      await onProposeAndApprove();
    } finally {
      setBusy(false);
    }
  };

  const handleDelay = async () => {
    setBusy(true);
    try {
      await onSimulateDelay(minutes);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <h2>Plan</h2>
      {error && <div className="error-banner">{error}</div>}
      <div className="plan-header">
        <h3>{part.description}</h3>
        <div className="sub">
          {part.tail_number} · needed at {part.station} · expires {part.expires_on} ({part.days_left}d)
        </div>
      </div>

      {loadingCandidates ? (
        <p className="empty-hint">Loading options…</p>
      ) : (
        <div className="candidate-list">
          {candidates.map((c, i) => (
            <div key={`${c.option}-${c.source}-${i}`} className={`candidate-card ${i === 0 ? "best" : ""}`}>
              <div className="row">
                <span className="option-badge">
                  {i === 0 ? "★ " : ""}
                  {c.option}
                </span>
                <span>${c.cost.toFixed(0)}</span>
              </div>
              <div className="row">
                <span>
                  {c.source}
                  {c.flight_number ? ` · ${c.flight_number}` : ""}
                </span>
                <span>risk {(c.risk_score * 100).toFixed(0)}%</span>
              </div>
              <div className="row">
                <span>arrives {formatEta(c.eta)}</span>
              </div>
              <div className="detail">{c.detail}</div>
            </div>
          ))}
          {candidates.length === 0 && <p className="empty-hint">No feasible option before the deadline.</p>}
        </div>
      )}

      {!plan && candidates.length > 0 && (
        <button onClick={handlePropose} disabled={busy}>
          {busy ? "Working…" : "Propose & Approve Plan"}
        </button>
      )}

      {plan && (
        <div className="plan-summary">
          <div className="row">
            <span className="option-badge">{plan.option}</span>
            <span className="status-badge" data-status={plan.status}>
              {plan.status}
            </span>
          </div>
          <div className="row" style={{ marginTop: "0.35rem" }}>
            <span>
              {plan.source}
              {plan.flight_number ? ` · ${plan.flight_number}` : ""}
            </span>
            <span>${plan.cost.toFixed(0)}</span>
          </div>
          <div className="plan-reason">"{plan.reason}"</div>

          {canDelay && plan.flight_number && (
            <div className="delay-controls">
              <input
                type="number"
                value={minutes}
                min={1}
                onChange={(e) => setMinutes(Number(e.target.value))}
              />
              <span style={{ fontSize: "0.75rem", color: "#94a3b8" }}>min delay on {plan.flight_number}</span>
              <button className="secondary" onClick={handleDelay} disabled={busy}>
                {busy ? "Working…" : "Simulate Delay"}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
