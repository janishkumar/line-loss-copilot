// Types mirror src/linecopilot/api/models.py.
export type Status = "ok" | "insufficient_evidence" | "out_of_scope";

export interface Citation {
  raw_table: string;
  source_file: string;
  raw_row_id: number;
  event_id: number | null;
  field: string | null;
}

export interface Window {
  start: string | null;
  end: string | null;
  line_id: string | null;
  machine_id: string | null;
  group: string | null;
}

export interface Result<T> {
  status: Status;
  data: T | null;
  citations: Citation[];
  citation_count: number;
  window: Window | null;
  assumptions: string[];
  missing: string | null;
}

export interface LineInfo {
  line_id: string;
  source_system: string;
  source_timezone: string;
  first_ts: string;
  last_ts: string;
  event_count: number;
  machines: string[];
}

export interface MachineInfo {
  machine_id: string;
  line_id: string;
  source_system: string;
  first_ts: string;
  last_ts: string;
  event_count: number;
}

export interface AssetsData {
  lines: LineInfo[];
  machines: MachineInfo[];
}

export interface OeeRow {
  key: string;
  start: string | null;
  metrics: Record<string, number | null>;
  details: Record<string, string | number | null>;
  citations: Citation[];
  citation_count: number;
}

export interface OeeData {
  source_system: string;
  group: string;
  rows: OeeRow[];
  row_count: number;
  rows_truncated: boolean;
}

export interface GapStats {
  n: number;
  mean_abs: number | null;
  median_abs: number | null;
  max_abs: number | null;
  share_within_2pts: number | null;
  share_within_5pts: number | null;
  mean_signed: number | null;
}

export interface PeriodSummary {
  n_published: number;
  n_matched: number;
  n_no_stops: number;
  n_no_published: number;
  availability: GapStats;
  oee: GapStats;
}

export interface ValidationShift {
  shift_id: string;
  shift_date: string;
  period: "before" | "after";
  planned_s_published: number | null;
  availability_calc: number | null;
  availability_pub: number | null;
  availability_gap: number | null;
  oee_calc_with_pub_pq: number | null;
  oee_pub: number | null;
  oee_gap: number | null;
  match_status: string;
}

export interface ValidationData {
  windows: Record<string, { first: string; last: string }>;
  periods: Record<string, PeriodSummary>;
  shifts: ValidationShift[];
}

export interface SourceData {
  event_id: number;
  event_key: string;
  raw_table: string;
  source_file: string;
  rows: Record<string, unknown>[];
}

async function get<T>(path: string, params?: Record<string, string | number | undefined>) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params ?? {})) if (v !== undefined) qs.set(k, String(v));
  const url = `/api${path}${qs.size ? `?${qs}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${url}`);
  return (await res.json()) as Result<T>;
}

export const getAssets = () => get<AssetsData>("/assets");
export const getOee = (p: {
  line_id?: string;
  machine_id?: string;
  group: string;
  limit?: number;
}) => get<OeeData>("/oee", p);
export const getValidation = () => get<ValidationData>("/oee/validation");
export const getSource = (eventId: number | string) => get<SourceData>(`/events/${eventId}/source`);
