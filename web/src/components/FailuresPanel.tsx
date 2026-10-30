import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api";
import type { Plan, RaisedBy, ShippingRequest } from "../api";

interface Props {
  onReported: () => void;
}

export function FailuresPanel({ onReported }: Props) {
  const [requests, setRequests] = useState<ShippingRequest[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ request: ShippingRequest; plan: Plan | null } | null>(null);

  const [tailNumber, setTailNumber] = useState("");
  const [station, setStation] = useState("");
  const [partNumber, setPartNumber] = useState("");
  const [reportedBy, setReportedBy] = useState<RaisedBy>("maintenance_control");
  const [notes, setNotes] = useState("");

  const refresh = () => {
    api.getRequests().then(setRequests).catch((e) => setError(String(e)));
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.reportFailure({
        tail_number: tailNumber,
        station,
        part_number: partNumber,
        reported_by: reportedBy,
        notes: notes.trim() || undefined,
      });
      setResult(res);
      refresh();
      onReported();
      setTailNumber("");
      setStation("");
      setPartNumber("");
      setNotes("");
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  const openRequests = requests.filter((r) => r.status === "open" || r.status === "planned");

  return (
    <div className="panel failures-panel">
      <h2>Report Failure</h2>
      {error && <div className="error-banner">{error}</div>}
      <form className="failure-form" onSubmit={handleSubmit}>
        <input
          placeholder="Tail number (e.g. N501EV)"
          value={tailNumber}
          onChange={(e) => setTailNumber(e.target.value)}
          required
        />
        <input placeholder="Station (e.g. CVG)" value={station} onChange={(e) => setStation(e.target.value)} required />
        <input
          placeholder="Part number (e.g. OXY-BTL-02)"
          value={partNumber}
          onChange={(e) => setPartNumber(e.target.value)}
          required
        />
        <select value={reportedBy} onChange={(e) => setReportedBy(e.target.value as RaisedBy)}>
          <option value="maintenance_control">Maintenance Control</option>
          <option value="stores">Stores</option>
        </select>
        <textarea placeholder="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
        <button type="submit" disabled={busy}>
          {busy ? "Working…" : "Report Failure"}
        </button>
      </form>

      {result && (
        <div className={`verify-result-banner ${result.plan ? "matched" : "mismatched"}`}>
          <div className="row">
            <strong>{result.plan ? "Plan ready" : "No plan found"}</strong>
            <button className="secondary" onClick={() => setResult(null)}>
              Dismiss
            </button>
          </div>
          {result.plan ? (
            <p className="empty-hint">
              {result.plan.option} from {result.plan.source} — {result.plan.status} ({result.plan.priority})
            </p>
          ) : (
            <p className="empty-hint">No feasible option found yet — request stays open.</p>
          )}
        </div>
      )}

      <div className="failures-subheading">Shipping Requests</div>
      {openRequests.length === 0 ? (
        <p className="empty-hint">No open requests.</p>
      ) : (
        <div className="request-list">
          {openRequests.map((r) => (
            <div key={r.id} className="request-card">
              <div className="row">
                {r.trigger === "failure" && <span className="failure-tag">Failure</span>}
                <span className="option-badge">{r.priority}</span>
                <span>{r.part_number}</span>
              </div>
              <div className="verify-task-record">
                {r.station_needed} · {r.status}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
