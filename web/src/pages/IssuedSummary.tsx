import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { PartRequest } from "../api";

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function IssuedSummary() {
  const [issued, setIssued] = useState<PartRequest[]>([]);
  const [flagged, setFlagged] = useState<PartRequest[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getPartRequests("issued").then(setIssued).catch((e) => setError(String(e)));
    api.getPartRequests("flagged").then(setFlagged).catch((e) => setError(String(e)));
  }, []);

  return (
    <div className="pickslip-page">
      <header className="pickslip-header">
        <Link to="/" className="back-link">
          ← Dashboard
        </Link>
        <h1>Issued Summary</h1>
      </header>
      {error && <div className="error-banner">{error}</div>}

      <h2 className="issued-section-title">Issued</h2>
      {issued.length === 0 ? (
        <p className="empty-hint">Nothing issued yet.</p>
      ) : (
        <table className="issued-table">
          <thead>
            <tr>
              <th>Part</th>
              <th>Tail</th>
              <th>Mechanic</th>
              <th>Location · Serial</th>
              <th>Issued</th>
              <th>Photo-verified</th>
            </tr>
          </thead>
          <tbody>
            {issued.map((r) => (
              <tr key={r.id}>
                <td>{r.part_number}</td>
                <td>{r.tail_number}</td>
                <td>{r.mechanic}</td>
                <td>
                  {r.picked_location} · {r.picked_serial}
                </td>
                <td>{formatTime(r.issued_at)}</td>
                <td>{r.photo_filename ? "Yes" : "No"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2 className="issued-section-title">Flagged discrepancies</h2>
      {flagged.length === 0 ? (
        <p className="empty-hint">No discrepancies caught at pick.</p>
      ) : (
        <table className="issued-table">
          <thead>
            <tr>
              <th>Part</th>
              <th>Station</th>
              <th>Mechanic</th>
              <th>Reason</th>
              <th>Suggested next</th>
            </tr>
          </thead>
          <tbody>
            {flagged.map((r) => (
              <tr key={r.id}>
                <td>{r.part_number}</td>
                <td>{r.station}</td>
                <td>{r.mechanic}</td>
                <td>{r.flagged_reason}</td>
                <td>{r.suggested_next}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
