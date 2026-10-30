import { useEffect, useState } from "react";
import { api } from "../api";
import type { ExpiringLotAction } from "../api";

interface Props {
  onApproved: () => void;
}

const ACTION_LABELS: Record<string, string> = { use: "Use", move: "Move", replace: "Replace" };

export function ExpiringLotsPanel({ onApproved }: Props) {
  const [actions, setActions] = useState<ExpiringLotAction[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const refresh = () => {
    api.getExpiringLots().then(setActions).catch((e) => setError(String(e)));
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleApprove = async (action: ExpiringLotAction) => {
    setBusyId(action.id);
    setError(null);
    try {
      await api.approveExpiringLotAction(action.id);
      refresh();
      onApproved();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusyId(null);
    }
  };

  const pending = actions.filter((a) => a.status === "pending");

  return (
    <div className="panel expiring-lots-panel">
      <h2>Expiring Lots</h2>
      {error && <div className="error-banner">{error}</div>}
      {pending.length === 0 ? (
        <p className="empty-hint">No expiring lots need a decision right now.</p>
      ) : (
        <div className="lot-list">
          {pending.map((a) => (
            <div key={a.id} className="lot-card">
              <div className="row">
                <span className={`lot-action-badge lot-action-${a.action}`}>{ACTION_LABELS[a.action]}</span>
                <span className="lot-id">{a.inventory_serial}</span>
              </div>
              <div className="lot-reason">{a.reason}</div>
              <button className="secondary" disabled={busyId === a.id} onClick={() => handleApprove(a)}>
                {busyId === a.id ? "Working…" : "Approve"}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
