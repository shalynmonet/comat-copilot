import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, SAMPLE_PICK_PHOTOS } from "../api";
import type { PartRequest } from "../api";

export function PickSlip() {
  const [requests, setRequests] = useState<PartRequest[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [lastResult, setLastResult] = useState<PartRequest | null>(null);

  const refresh = () => {
    api.getPartRequests("open").then(setRequests).catch((e) => setError(String(e)));
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleUpload = async (request: PartRequest, file: File) => {
    setBusyId(request.id);
    setError(null);
    try {
      const result = await api.submitPickPhoto(request.id, file);
      setLastResult(result);
      setActiveId(null);
      refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusyId(null);
    }
  };

  const useSample = async (request: PartRequest, kind: "match" | "mismatch") => {
    const filename = SAMPLE_PICK_PHOTOS[kind];
    const blob = await fetch(api.demoAssetUrl(filename)).then((r) => r.blob());
    await handleUpload(request, new File([blob], filename, { type: blob.type || "image/jpeg" }));
  };

  return (
    <div className="pickslip-page">
      <header className="pickslip-header">
        <Link to="/" className="back-link">
          ← Dashboard
        </Link>
        <h1>PickSlip</h1>
      </header>
      {error && <div className="error-banner">{error}</div>}

      {lastResult && (
        <div className={`verify-result-banner ${lastResult.status === "issued" ? "matched" : "mismatched"}`}>
          <div className="row">
            <strong>{lastResult.status === "issued" ? "Issued" : "Flagged"}</strong>
            <button className="secondary" onClick={() => setLastResult(null)}>
              Dismiss
            </button>
          </div>
          {lastResult.status === "issued" ? (
            <p className="empty-hint">
              Picked {lastResult.picked_location} · serial {lastResult.picked_serial}
            </p>
          ) : (
            <>
              <p className="empty-hint">{lastResult.flagged_reason}</p>
              {lastResult.suggested_next && <p className="empty-hint">Suggestion: {lastResult.suggested_next}</p>}
            </>
          )}
        </div>
      )}

      {requests.length === 0 ? (
        <p className="empty-hint">No open part requests.</p>
      ) : (
        <div className="pick-list">
          {requests.map((r) => (
            <div key={r.id} className="pick-card">
              <div className="pick-card-main">
                <div className="pick-part">{r.part_number}</div>
                <div className="pick-sub">
                  {r.tail_number} · {r.mechanic}
                </div>
                <div className="pick-location">
                  Expected: {r.expected_location ?? "unknown"} at {r.station}
                </div>
              </div>
              {activeId === r.id ? (
                <div className="pick-actions">
                  <label className="file-upload-btn pick-upload-btn">
                    Take / upload photo
                    <input
                      type="file"
                      accept="image/*"
                      capture="environment"
                      hidden
                      disabled={busyId === r.id}
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) handleUpload(r, f);
                      }}
                    />
                  </label>
                  <button className="secondary" disabled={busyId === r.id} onClick={() => useSample(r, "match")}>
                    Sample: match
                  </button>
                  <button className="secondary" disabled={busyId === r.id} onClick={() => useSample(r, "mismatch")}>
                    Sample: mismatch
                  </button>
                  <button className="secondary" onClick={() => setActiveId(null)}>
                    Cancel
                  </button>
                </div>
              ) : (
                <button className="pick-open-btn" onClick={() => setActiveId(r.id)}>
                  Pick this
                </button>
              )}
              {busyId === r.id && <p className="empty-hint">Reading tag…</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
