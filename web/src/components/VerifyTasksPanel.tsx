import { useEffect, useState } from "react";
import type { InventoryItem, VerifyTask } from "../api";
import { api, SAMPLE_TAG_PHOTOS } from "../api";

interface Props {
  onResolved: () => void;
  refreshSignal: number;
}

interface Resolution {
  task: VerifyTask;
  item: InventoryItem;
}

function confidenceLevel(c: number): "low" | "mid" | "high" {
  if (c < 0.4) return "low";
  if (c < 0.6) return "mid";
  return "high";
}

function compareRow(label: string, record: string, extracted: string | null, matches: boolean) {
  return (
    <div key={label} className={`verify-compare-row ${matches ? "" : "mismatch"}`}>
      <span className="verify-compare-label">{label}</span>
      <span>{record}</span>
      <span>{extracted ?? "unreadable"}</span>
    </div>
  );
}

export function VerifyTasksPanel({ onResolved, refreshSignal }: Props) {
  const [tasks, setTasks] = useState<VerifyTask[]>([]);
  const [items, setItems] = useState<Record<string, InventoryItem>>({});
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastResolution, setLastResolution] = useState<Resolution | null>(null);

  const refresh = () => {
    api
      .getVerifyTasks("open")
      .then(async (openTasks) => {
        setTasks(openTasks);
        const entries = await Promise.all(
          openTasks.map(async (t) => [t.inventory_serial, await api.getInventoryItem(t.inventory_serial)] as const),
        );
        setItems(Object.fromEntries(entries));
      })
      .catch((e) => setError(String(e)));
  };

  useEffect(() => {
    refresh();
  }, [refreshSignal]);

  const handleUpload = async (task: VerifyTask, file: File) => {
    setBusyId(task.id);
    setError(null);
    try {
      const result = await api.submitVerifyTaskPhoto(task.id, file, "Stores");
      setLastResolution({ task: result.task, item: result.inventory_item });
      refresh();
      onResolved();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusyId(null);
    }
  };

  const useSample = async (task: VerifyTask, kind: "match" | "mismatch") => {
    const filename = SAMPLE_TAG_PHOTOS[kind];
    const blob = await fetch(api.demoAssetUrl(filename)).then((r) => r.blob());
    await handleUpload(task, new File([blob], filename, { type: blob.type || "image/jpeg" }));
  };

  return (
    <div className="panel verify-tasks-panel">
      <h2>Verify Tasks</h2>
      {error && <div className="error-banner">{error}</div>}

      {lastResolution && (
        <div className={`verify-result-banner ${lastResolution.task.status}`}>
          <div className="row">
            <strong>{lastResolution.task.status === "matched" ? "Match" : "Mismatch"}</strong>
            <button className="secondary" onClick={() => setLastResolution(null)}>
              Dismiss
            </button>
          </div>
          <div className="verify-compare-row header">
            <span />
            <span>Record</span>
            <span>Extracted from photo</span>
          </div>
          {compareRow(
            "Part Number",
            lastResolution.item.part_number,
            lastResolution.task.extracted_part_number,
            lastResolution.task.extracted_part_number === lastResolution.item.part_number,
          )}
          {compareRow(
            "Serial",
            lastResolution.item.serial,
            lastResolution.task.extracted_serial,
            lastResolution.task.extracted_serial === lastResolution.item.serial,
          )}
          {compareRow(
            "Condition",
            lastResolution.item.condition,
            lastResolution.task.extracted_condition,
            lastResolution.task.extracted_condition === lastResolution.item.condition,
          )}
          <p className="empty-hint">
            {lastResolution.task.status === "matched"
              ? "Confidence raised, plan continues."
              : "Flagged phantom -- plan re-routed to the next source."}
          </p>
        </div>
      )}

      {tasks.length === 0 ? (
        <p className="empty-hint">No spares need photo verification right now.</p>
      ) : (
        <div className="verify-task-list">
          {tasks.map((task) => {
            const item = items[task.inventory_serial];
            return (
              <div key={task.id} className="verify-task-card">
                <div className="row">
                  <span className="confidence-badge" data-level={confidenceLevel(task.confidence_at_creation)}>
                    confidence {(task.confidence_at_creation * 100).toFixed(0)}%
                  </span>
                  <span>{item ? `${item.part_number} · ${item.station}` : "…"}</span>
                </div>
                <div className="verify-task-reason">{task.reason}</div>
                {item && (
                  <div className="verify-task-record">
                    on record: serial {item.serial}, {item.condition}
                  </div>
                )}
                <div className="verify-task-actions">
                  <label className="secondary file-upload-btn">
                    Upload photo
                    <input
                      type="file"
                      accept="image/*"
                      hidden
                      disabled={busyId === task.id}
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) handleUpload(task, f);
                      }}
                    />
                  </label>
                  <button className="secondary" disabled={busyId === task.id} onClick={() => useSample(task, "match")}>
                    Use sample (match)
                  </button>
                  <button
                    className="secondary"
                    disabled={busyId === task.id}
                    onClick={() => useSample(task, "mismatch")}
                  >
                    Use sample (mismatch)
                  </button>
                </div>
                {busyId === task.id && <p className="empty-hint">Reading tag…</p>}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
