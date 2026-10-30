import { useEffect, useState } from "react";
import { api } from "../api";
import type { StockingSuggestion } from "../api";

interface Props {
  onApproved: () => void;
}

export function StockingPanel({ onApproved }: Props) {
  const [suggestions, setSuggestions] = useState<StockingSuggestion[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const refresh = () => {
    api.getStocking().then(setSuggestions).catch((e) => setError(String(e)));
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleApprove = async (suggestion: StockingSuggestion) => {
    setBusyId(suggestion.id);
    setError(null);
    try {
      await api.approveStockingSuggestion(suggestion.id);
      refresh();
      onApproved();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusyId(null);
    }
  };

  const pending = suggestions.filter((s) => s.status === "pending");

  return (
    <div className="panel stocking-panel">
      <h2>Stocking Suggestions</h2>
      {error && <div className="error-banner">{error}</div>}
      {pending.length === 0 ? (
        <p className="empty-hint">No stocking gaps found right now.</p>
      ) : (
        <div className="lot-list">
          {pending.map((s) => (
            <div key={s.id} className="lot-card">
              <div className="row">
                <span className="lot-action-badge lot-action-move">{s.station}</span>
                <span className="lot-id">
                  {s.part_number} · {s.fleet_type}
                </span>
              </div>
              <div className="lot-reason">{s.reason}</div>
              <button className="secondary" disabled={busyId === s.id} onClick={() => handleApprove(s)}>
                {busyId === s.id ? "Working…" : "Approve"}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
