import { useState } from "react";
import type { FieldSpec, ShipmentDraft } from "../api";
import { api } from "../api";

interface Props {
  drafts: ShipmentDraft[];
  fieldSpecs: FieldSpec[];
  onSubmit: (draftId: number) => Promise<void>;
  error: string | null;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function draftLines(draft: ShipmentDraft, specs: FieldSpec[]): string[] {
  return specs.map((spec) => `${spec.label}: ${formatValue(draft.fields[spec.name])}`);
}

export function ShipmentDraftPanel({ drafts, fieldSpecs, onSubmit, error }: Props) {
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  if (drafts.length === 0 || fieldSpecs.length === 0) {
    return (
      <div className="panel shipment-draft-panel">
        <h2>SAFE Shipment Draft</h2>
        <p className="empty-hint">Approve a plan to build a SAFE-ready shipment draft.</p>
      </div>
    );
  }

  const current = drafts[drafts.length - 1];
  const superseded = drafts.slice(0, -1);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(draftLines(current, fieldSpecs).join("\n"));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const handleSubmit = async () => {
    setBusy(true);
    try {
      await onSubmit(current.id);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel shipment-draft-panel">
      <h2>SAFE Shipment Draft</h2>
      {error && <div className="error-banner">{error}</div>}

      <div className="draft-card">
        <div className="row">
          <span className="status-badge" data-status={current.status}>
            {current.status}
          </span>
          {current.missing_fields.length > 0 && (
            <span className="missing-count">{current.missing_fields.length} missing</span>
          )}
        </div>

        <div className="draft-fields">
          {fieldSpecs.map((spec) => {
            const missing = current.missing_fields.includes(spec.name);
            return (
              <div key={spec.name} className={`draft-field-row ${missing ? "missing" : ""}`}>
                <span className="draft-field-label">{spec.label}</span>
                <span className="draft-field-value">{formatValue(current.fields[spec.name])}</span>
              </div>
            );
          })}
        </div>

        <div className="draft-actions">
          <button className="secondary" onClick={handleCopy}>
            {copied ? "Copied!" : "Copy to SAFE"}
          </button>
          <button className="secondary" onClick={() => window.open(api.exportShipmentUrl(current.id, "csv"), "_blank")}>
            Export CSV
          </button>
          {current.status === "ready" && (
            <button onClick={handleSubmit} disabled={busy}>
              {busy ? "Submitting…" : "Mark Submitted"}
            </button>
          )}
          {current.status === "submitted" && <span className="current-tag">submitted to SAFE/iCargo</span>}
          {current.status === "draft" && <span className="empty-hint">fill in missing fields before submitting</span>}
          {current.status === "superseded" && (
            <span className="empty-hint">superseded — approve the new recommendation to build a fresh draft</span>
          )}
        </div>
      </div>

      {superseded.length > 0 && (
        <div className="superseded-drafts">
          <div className="superseded-heading">Superseded drafts</div>
          {superseded.map((d) => (
            <div key={d.id} className="draft-card superseded">
              <div className="row">
                <span className="status-badge" data-status={d.status}>
                  {d.status}
                </span>
                <span className="superseded-link">→ replaced by current draft</span>
              </div>
              <div className="draft-field-row">
                <span className="draft-field-label">AWB Number</span>
                <span className="draft-field-value">{formatValue(d.fields.awb_number)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
