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
}

export type OverrideReason = "flight_usually_full" | "preferred_vendor" | "spare_needed_elsewhere" | "other";

export const OVERRIDE_REASON_LABELS: Record<OverrideReason, string> = {
  flight_usually_full: "Flight usually full",
  preferred_vendor: "Preferred vendor",
  spare_needed_elsewhere: "Spare needed elsewhere",
  other: "Other",
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
  event_type: "created" | "re-routed" | "approved" | "overridden" | "shipped" | "installed";
  created_at: string;
  detail: string | null;
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
    request<{ flight: Flight; replanned_plans: Plan[] }>(`/flights/${id}/delay`, {
      method: "POST",
      body: JSON.stringify({ minutes }),
    }),
  getEvents: (planId?: number) => request<PlanEvent[]>(`/events${planId ? `?plan_id=${planId}` : ""}`),
};
