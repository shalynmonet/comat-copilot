import { useState } from "react";
import type { Candidate, ExpiringPart, OverrideReason, Plan } from "../api";
import { OVERRIDE_REASON_LABELS } from "../api";

interface Props {
  part: ExpiringPart | null;
  candidates: Candidate[];
  loadingCandidates: boolean;
  plan: Plan | null;
  canDelay: boolean;
  onApproveTop: () => Promise<void>;
  onChooseAlternative: (candidate: Candidate, reason: OverrideReason, note: string) => Promise<void>;
  onApprovePending: () => Promise<void>;
  onSimulateDelay: (minutes: number) => Promise<void>;
  error: string | null;
}

const EDITABLE_STATUSES = new Set(["proposed", "approved", "at_risk", "re_routed"]);
const OVERRIDE_REASONS: OverrideReason[] = [
  "flight_usually_full",
  "preferred_vendor",
  "spare_needed_elsewhere",
  "other",
];

function formatEta(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function candidateKey(c: { option: string; source: string | null; flight_number: string | null }): string {
  return `${c.option}|${c.source ?? ""}|${c.flight_number ?? ""}`;
}

export function PlanCard({
  part,
  candidates,
  loadingCandidates,
  plan,
  canDelay,
  onApproveTop,
  onChooseAlternative,
  onApprovePending,
  onSimulateDelay,
  error,
}: Props) {
  const [minutes, setMinutes] = useState(600);
  const [busy, setBusy] = useState(false);
  const [overridingKey, setOverridingKey] = useState<string | null>(null);
  const [overrideReason, setOverrideReason] = useState<OverrideReason>("flight_usually_full");
  const [overrideNote, setOverrideNote] = useState("");

  if (!part) {
    return (
      <div className="panel">
        <h2>Plan</h2>
        <p className="empty-hint">Select an expiring part from the queue to see its options.</p>
      </div>
    );
  }

  const editable = !plan || EDITABLE_STATUSES.has(plan.status);
  const feasible = candidates.filter((c) => !c.disqualified);
  const disqualified = candidates.filter((c) => c.disqualified);
  const topKey = feasible[0] ? candidateKey(feasible[0]) : null;
  const selectedKey = plan ? candidateKey(plan) : null;
  const hasPending = !!(plan && plan.pending_option);

  const startOverride = (c: Candidate) => {
    setOverridingKey(candidateKey(c));
    setOverrideReason("flight_usually_full");
    setOverrideNote("");
  };

  const cancelOverride = () => setOverridingKey(null);

  const confirmOverride = async (c: Candidate) => {
    setBusy(true);
    try {
      await onChooseAlternative(c, overrideReason, overrideNote);
      setOverridingKey(null);
    } finally {
      setBusy(false);
    }
  };

  const handleApproveTop = async () => {
    setBusy(true);
    try {
      await onApproveTop();
    } finally {
      setBusy(false);
    }
  };

  const handleApprovePending = async () => {
    setBusy(true);
    try {
      await onApprovePending();
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

      {plan && plan.status === "at_risk" && (
        <div className="at-risk-banner">
          <div className="row">
            <span className="status-badge" data-status="at_risk">
              at risk
            </span>
            <span>a booked flight changed</span>
          </div>
          {hasPending ? (
            <>
              <div className="pending-rec">
                <div className="row">
                  <span className="option-badge">new rec: {plan.pending_option}</span>
                  <span>${plan.pending_cost?.toFixed(0)}</span>
                </div>
                <div className="row">
                  <span>
                    {plan.pending_source}
                    {plan.pending_flight_number ? ` · ${plan.pending_flight_number}` : ""}
                  </span>
                  <span>risk {((plan.pending_risk_score ?? 0) * 100).toFixed(0)}%</span>
                </div>
                <div className="plan-reason">"{plan.pending_reason}"</div>
              </div>
              <button onClick={handleApprovePending} disabled={busy}>
                {busy ? "Working…" : "Approve New Recommendation"}
              </button>
            </>
          ) : (
            <p className="empty-hint">No feasible alternative remains — pick an option below.</p>
          )}
        </div>
      )}

      {loadingCandidates ? (
        <p className="empty-hint">Loading options…</p>
      ) : (
        <div className="candidate-list">
          {feasible.map((c) => {
            const key = candidateKey(c);
            const isTop = key === topKey;
            const isSelected = key === selectedKey;
            const isOverriding = overridingKey === key;
            return (
              <div key={key} className={`candidate-card ${isTop ? "best" : ""} ${isSelected ? "selected" : ""}`}>
                <div className="row">
                  <span className="option-badge">
                    {isSelected ? "✓ " : isTop ? "★ " : ""}
                    {c.option}
                  </span>
                  <span>${c.cost.toFixed(0)}</span>
                </div>
                <div className="row">
                  <span>
                    {c.source}
                    {c.flight_number ? ` · ${c.flight_number}` : ""}
                  </span>
                  <span>risk {((c.risk_score ?? 0) * 100).toFixed(0)}%</span>
                </div>
                <div className="row">
                  <span>arrives {formatEta(c.eta)}</span>
                </div>
                <div className="detail">{c.detail}</div>
                {c.is_dangerous_goods && <div className="dg-badge">⚠ Dangerous goods</div>}
                {isSelected && <div className="current-tag">current plan</div>}

                {editable &&
                  !isSelected &&
                  !isOverriding &&
                  (!plan && isTop ? (
                    <button onClick={handleApproveTop} disabled={busy}>
                      {busy ? "Working…" : "Approve"}
                    </button>
                  ) : (
                    <button className="secondary" onClick={() => startOverride(c)} disabled={busy}>
                      Choose this instead
                    </button>
                  ))}

                {isOverriding && (
                  <div className="override-form">
                    <select
                      value={overrideReason}
                      onChange={(e) => setOverrideReason(e.target.value as OverrideReason)}
                    >
                      {OVERRIDE_REASONS.map((r) => (
                        <option key={r} value={r}>
                          {OVERRIDE_REASON_LABELS[r]}
                        </option>
                      ))}
                    </select>
                    {overrideReason === "other" && (
                      <textarea
                        placeholder="Say why…"
                        value={overrideNote}
                        onChange={(e) => setOverrideNote(e.target.value)}
                      />
                    )}
                    <div className="override-actions">
                      <button
                        onClick={() => confirmOverride(c)}
                        disabled={busy || (overrideReason === "other" && overrideNote.trim() === "")}
                      >
                        {busy ? "Working…" : "Confirm"}
                      </button>
                      <button className="secondary" onClick={cancelOverride} disabled={busy}>
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}

          {disqualified.map((c) => (
            <div key={`${candidateKey(c)}-dq`} className="candidate-card disqualified">
              <div className="row">
                <span className="option-badge">{c.option}</span>
                <span>${c.cost.toFixed(0)}</span>
              </div>
              <div className="row">
                <span>
                  {c.source}
                  {c.flight_number ? ` · ${c.flight_number}` : ""}
                </span>
              </div>
              <div className="disqualified-reason">Disqualified: {c.disqualified_reason}</div>
              {c.is_dangerous_goods && <div className="dg-badge">⚠ Dangerous goods</div>}
            </div>
          ))}

          {feasible.length === 0 && disqualified.length === 0 && (
            <p className="empty-hint">No options found for this part.</p>
          )}
        </div>
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
