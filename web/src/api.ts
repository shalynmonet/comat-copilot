const API_URL = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

export interface Station {
  code: string;
  name: string;
  lat: number;
  lon: number;
  has_maintenance: boolean;
  stores_capacity: number;
}

export interface ExpiringPart {
  serial: string;
  part_number: string;
  description: string;
  tail_number: string;
  station: string;
  position: string;
  expires_on: string;
  days_left: number;
}

export type PlanOption = "COMAT" | "transfer" | "buy";
export type PlanStatus =
  | "proposed"
  | "approved"
  | "at_risk"
  | "re_routed"
  | "pending_verification"
  | "shipped"
  | "installed"
  | "cancelled";

export interface Candidate {
  option: PlanOption;
  source: string;
  flight_number: string | null;
  cost: number;
  eta: string;
  risk_score: number | null;
  score: number | null;
  detail: string;
  disqualified: boolean;
  disqualified_reason: string | null;
  is_dangerous_goods: boolean;
  spare_serial: string | null;
  confidence: number | null;
  low_confidence_reason: string | null;
}

export type OverrideReason = "flight_usually_full" | "preferred_vendor" | "spare_needed_elsewhere" | "other";

export const OVERRIDE_REASON_LABELS: Record<OverrideReason, string> = {
  flight_usually_full: "Flight usually full",
  preferred_vendor: "Preferred vendor",
  spare_needed_elsewhere: "Spare needed elsewhere",
  other: "Other",
};

export type Priority = "AOG" | "MRD" | "MRX" | "STD";
export type CommodityProfile = "critical_planeside" | "critical_cargo" | "low_cargo";
export type HandoffRoute = "plane_side" | "to_cargo";
export type ShipmentStatus =
  | "booked"
  | "awb_issued"
  | "load_plan_updated"
  | "accepted"
  | "screened"
  | "loaded"
  | "handed_to_cargo"
  | "delivered";

export const TRACKER_STEPS: Record<HandoffRoute, { step: ShipmentStatus; label: string }[]> = {
  plane_side: [
    { step: "booked", label: "Booked" },
    { step: "awb_issued", label: "AWB Issued" },
    { step: "load_plan_updated", label: "Load Plan Updated" },
    { step: "accepted", label: "Accepted" },
    { step: "screened", label: "Screened" },
    { step: "loaded", label: "Loaded" },
    { step: "delivered", label: "Delivered" },
  ],
  to_cargo: [
    { step: "booked", label: "Booked" },
    { step: "awb_issued", label: "AWB Issued" },
    { step: "handed_to_cargo", label: "Handed to Cargo" },
    { step: "delivered", label: "Delivered" },
  ],
};

export interface Plan {
  id: number;
  installed_serial: string;
  option: PlanOption;
  source: string | null;
  flight_number: string | null;
  cost: number;
  risk_score: number;
  status: PlanStatus;
  reason: string | null;
  pending_option: PlanOption | null;
  pending_source: string | null;
  pending_flight_number: string | null;
  pending_cost: number | null;
  pending_risk_score: number | null;
  pending_reason: string | null;
  priority: Priority | null;
  commodity_profile: CommodityProfile | null;
  handling_codes: string[];
  handoff_route: HandoffRoute | null;
  is_ron_package: boolean;
  awb_number: string | null;
  shipment_status: ShipmentStatus | null;
  spare_serial: string | null;
}

export type ShipmentDraftStatus = "draft" | "ready" | "submitted" | "superseded";

export interface ShipmentDraft {
  id: number;
  plan_id: number;
  fields: Record<string, unknown>;
  status: ShipmentDraftStatus;
  missing_fields: string[];
  created_at: string;
  updated_at: string;
}

export interface FieldSpec {
  name: string;
  label: string;
  required: boolean;
}

export type RaisedBy = "maintenance_control" | "stores" | "copilot";
export type ShippingRequestStatus = "open" | "planned" | "drafted" | "submitted" | "fulfilled" | "cancelled";
export type ShippingRequestTrigger = "expiry" | "failure";

export interface ShippingRequest {
  id: number;
  part_number: string;
  serial: string | null;
  station_needed: string;
  needed_by: string;
  priority: Priority;
  raised_by: RaisedBy;
  status: ShippingRequestStatus;
  trigger: ShippingRequestTrigger;
  notes: string | null;
  plan_id: number | null;
  shipment_draft_id: number | null;
  created_at: string;
}

export interface Flight {
  id: number;
  flight_number: string;
  tail_number: string;
  origin: string;
  dest: string;
  sched_dep: string;
  sched_arr: string;
  status: "scheduled" | "delayed" | "departed" | "arrived" | "cancelled";
  cargo_capacity_lb: number;
}

export interface PlanEvent {
  id: number;
  plan_id: number;
  event_type:
    | "created"
    | "re-routed"
    | "approved"
    | "overridden"
    | "draft-created"
    | "verification-required"
    | "verified"
    | "phantom-flagged"
    | "shipped"
    | "installed";
  created_at: string;
  detail: string | null;
}

export type InventoryCondition = "serviceable" | "unserviceable" | "quarantined";

export interface InventoryItem {
  serial: string;
  part_number: string;
  station: string;
  condition: InventoryCondition;
  expires_on: string;
  last_counted_on: string;
  location: string | null;
  last_verified_at: string | null;
  verified_by: string | null;
  move_count_30d: number;
  confidence: number;
  phantom_flag: boolean;
}

export type VerifyTaskStatus = "open" | "matched" | "mismatched";

export interface VerifyTask {
  id: number;
  inventory_serial: string;
  plan_id: number;
  status: VerifyTaskStatus;
  reason: string;
  confidence_at_creation: number;
  created_at: string;
  resolved_at: string | null;
  photo_filename: string | null;
  extracted_part_number: string | null;
  extracted_serial: string | null;
  extracted_condition: string | null;
}

export interface StationDiscrepancy {
  station: string;
  discrepancy_rate: number;
}

export interface DashboardStats {
  aogs_avoided: number;
  planeside_runs_avoided: number;
  phantom_parts_caught: number;
  station_discrepancy_rates: StationDiscrepancy[];
  picks_verified_by_photo: number;
  discrepancies_caught_at_pick: number;
  shelf_life_value_saved: number;
  failure_response_time_median_minutes: number | null;
}

export type ExpiringLotActionType = "use" | "move" | "replace";
export type ExpiringLotActionStatus = "pending" | "approved";

export interface ExpiringLotAction {
  id: number;
  inventory_serial: string;
  lot: string;
  action: ExpiringLotActionType;
  reason: string;
  status: ExpiringLotActionStatus;
  plan_id: number | null;
  unit_cost: number;
  created_at: string;
  approved_at: string | null;
}

export type StockingSuggestionStatus = "pending" | "approved";

export interface StockingSuggestion {
  id: number;
  part_number: string;
  fleet_type: string;
  station: string;
  failure_count: number;
  reason: string;
  status: StockingSuggestionStatus;
  request_id: number | null;
  created_at: string;
  approved_at: string | null;
}

export const SAMPLE_TAG_PHOTOS = {
  match: "tag-ord-oxy-btl-02-match.jpg",
  mismatch: "tag-ord-oxy-btl-02-mismatch.jpg",
};

export const SAMPLE_PICK_PHOTOS = {
  match: "tag-pick-starter-gen-match.jpg",
  mismatch: "tag-pick-starter-gen-mismatch.jpg",
};

export type PartRequestStatus = "open" | "picked" | "issued" | "flagged";

export interface PartRequest {
  id: number;
  mechanic: string;
  tail_number: string;
  part_number: string;
  quantity: number;
  station: string;
  status: PartRequestStatus;
  expected_location: string | null;
  expected_serial: string | null;
  picked_location: string | null;
  picked_serial: string | null;
  photo_filename: string | null;
  flagged_reason: string | null;
  suggested_next: string | null;
  created_at: string;
  picked_at: string | null;
  issued_at: string | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${init?.method ?? "GET"} ${path} -> ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  getStations: () => request<Station[]>("/stations"),
  getExpiringParts: (windowDays?: number) =>
    request<ExpiringPart[]>(`/parts/expiring${windowDays ? `?window_days=${windowDays}` : ""}`),
  getCandidates: (serial: string) => request<Candidate[]>(`/plans/candidates/${encodeURIComponent(serial)}`),
  createPlan: (installedSerial: string) =>
    request<Plan>("/plans", { method: "POST", body: JSON.stringify({ installed_serial: installedSerial }) }),
  approvePlan: (id: number) => request<Plan>(`/plans/${id}/approve`, { method: "POST" }),
  chooseAlternative: (
    id: number,
    body: { option: PlanOption; source: string; flight_number: string | null; reason: OverrideReason; note?: string },
  ) => request<Plan>(`/plans/${id}/choose`, { method: "POST", body: JSON.stringify(body) }),
  getPlan: (id: number) => request<Plan>(`/plans/${id}`),
  getFlights: () => request<Flight[]>("/flights"),
  delayFlight: (id: number, minutes: number) =>
    request<{ flight: Flight; replanned_plans: Plan[] }>(`/flights/${id}/simulate-delay`, {
      method: "POST",
      body: JSON.stringify({ minutes }),
    }),
  getEvents: (planId?: number) => request<PlanEvent[]>(`/events${planId ? `?plan_id=${planId}` : ""}`),
  getFieldSpecs: () => request<FieldSpec[]>("/shipments/field-specs"),
  getShipments: (planId?: number) => request<ShipmentDraft[]>(`/shipments${planId ? `?plan_id=${planId}` : ""}`),
  submitShipment: (id: number) =>
    request<{ plan: Plan; draft: ShipmentDraft }>(`/shipments/${id}/submitted`, { method: "POST" }),
  exportShipmentUrl: (id: number, format: "json" | "csv") => `${API_URL}/shipments/${id}/export?format=${format}`,
  getRequests: (status?: ShippingRequestStatus) =>
    request<ShippingRequest[]>(`/requests${status ? `?status=${status}` : ""}`),
  getVerifyTasks: (status?: VerifyTaskStatus) =>
    request<VerifyTask[]>(`/verify-tasks${status ? `?status=${status}` : ""}`),
  getInventoryItem: (serial: string) => request<InventoryItem>(`/inventory/${encodeURIComponent(serial)}`),
  submitVerifyTaskPhoto: (taskId: number, photo: File, verifiedBy: string) => {
    const body = new FormData();
    body.append("photo", photo);
    body.append("verified_by", verifiedBy);
    return request<{ task: VerifyTask; inventory_item: InventoryItem; plan: Plan }>(
      `/verify-tasks/${taskId}/photo`,
      { method: "POST", body, headers: {} },
    );
  },
  demoAssetUrl: (filename: string) => `${API_URL}/demo-assets/${filename}`,
  getDashboardStats: () => request<DashboardStats>("/stats"),
  getPartRequests: (status?: PartRequestStatus) =>
    request<PartRequest[]>(`/part-requests${status ? `?status=${status}` : ""}`),
  createPartRequest: (body: { mechanic: string; tail_number: string; part_number: string; quantity: number; station: string }) =>
    request<PartRequest>("/part-requests", { method: "POST", body: JSON.stringify(body) }),
  submitPickPhoto: (requestId: number, photo: File) => {
    const body = new FormData();
    body.append("photo", photo);
    return request<PartRequest>(`/part-requests/${requestId}/photo`, { method: "POST", body, headers: {} });
  },
  getExpiringLots: () => request<ExpiringLotAction[]>("/expiring-lots"),
  approveExpiringLotAction: (id: number) =>
    request<ExpiringLotAction>(`/expiring-lots/${id}/approve`, { method: "POST" }),
  reportFailure: (body: { tail_number: string; station: string; part_number: string; reported_by: RaisedBy; notes?: string }) =>
    request<{ request: ShippingRequest; plan: Plan | null }>("/failures", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getStocking: (status?: StockingSuggestionStatus) =>
    request<StockingSuggestion[]>(`/stocking${status ? `?status=${status}` : ""}`),
  approveStockingSuggestion: (id: number) =>
    request<StockingSuggestion>(`/stocking/${id}/approve`, { method: "POST" }),
};
