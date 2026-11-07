// Types mirror the models in src/linecopilot/tools (re-exported by api/models.py).
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
  const res = await fetch(url, { credentials: "same-origin" });
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

export interface EvidenceRow {
  event_id: number;
  raw_table: string;
  source_file: string;
  source_row: number;
  raw: Record<string, unknown>;
}

export interface ShiftEvidenceData {
  shift_id: string;
  source_system: string;
  rows: EvidenceRow[];
  event_count: number;
  truncated: boolean;
  missing_rows?: { raw_table: string; source_file: string; raw_row_id: number }[];
}

export const getShiftEvidence = (shiftId: string) =>
  get<ShiftEvidenceData>(`/shifts/${encodeURIComponent(shiftId)}/evidence`);

// ---- Stage 2 tools: losses, reliability, risk, notes ----

export type Scope = {
  line_id?: string;
  machine_id?: string;
  start?: string;
  end?: string;
};

export interface ParetoRow {
  category: string;
  lost_s: number;
  stop_count: number;
  share: number;
  cumulative_share: number;
  citations: Citation[];
  citation_count: number;
}
export interface ParetoData {
  source_system: string;
  by: string;
  rows: ParetoRow[];
  total_lost_s: number;
  total_stop_count: number;
  other_lost_s: number;
  other_stop_count: number;
  other_categories: number;
}
export interface BreakdownData {
  source_system: string;
  rows: string;
  cols: string;
  row_keys: string[];
  col_keys: string[];
  cells: { row: string; col: string; lost_s: number; stop_count: number }[];
  total_lost_s: number;
  total_stop_count: number;
}
export interface RepeatChain {
  machine_id: string | null;
  line_id: string;
  key: string;
  count: number;
  first_start: string;
  last_end: string;
  lost_s: number;
  episode_ids: number[];
  citations: Citation[];
  citation_count: number;
}
export interface RepeatData {
  source_system: string;
  key: string;
  within_hours: number;
  min_repeats: number;
  chains: RepeatChain[];
  chain_count: number;
  chains_truncated: boolean;
  failure_count: number;
}
export interface ReliabilityRow {
  period: string;
  failure_count: number;
  stop_count: number;
  failure_s: number;
  run_s: number;
  mttr_s: number | null;
  mtbf_s: number | null;
  citations: Citation[];
  citation_count: number;
}
export interface ReliabilityData {
  source_system: string;
  group: string;
  rows: ReliabilityRow[];
}
export interface FeatureContribution {
  feature: string;
  contribution: number;
  value: number;
}
export interface MachineRisk {
  machine_id: string;
  t: string;
  covers_at: boolean;
  score: number;
  model_name: string;
  split: string;
  base_rate: number | null;
  alert_threshold: number | null;
  alert: boolean | null;
  top_features: FeatureContribution[];
  citations: Citation[];
  citation_count: number;
}
export interface RiskData {
  target: string;
  definition: string;
  rows: MachineRisk[];
}
export interface MetricRow {
  target: string;
  model_name: string;
  split: string;
  metric: string;
  value: number | null;
  machine_id: string | null;
  created_at: string;
}
export interface RiskMetricsData {
  rows: MetricRow[];
}
export interface NoteHit {
  note_id: number;
  event_id: number;
  start_ts: string;
  machine_id: string | null;
  reason: string | null;
  original_text: string;
  language: string;
  translation: { text: string; model_name: string; machine_translated: boolean } | null;
}
export interface NotesData {
  query: string;
  hits: NoteHit[];
  total: number;
  limit: number;
  truncated: boolean;
}

export const getPareto = (p: Scope & { by: string }) => get<ParetoData>("/losses/pareto", p);
export const getBreakdown = (p: Scope & { rows: string; cols: string }) =>
  get<BreakdownData>("/losses/breakdown", p);
export const getRepeats = (p: Scope & { key?: string }) => get<RepeatData>("/losses/repeats", p);
export const getReliability = (p: Scope & { group: string }) =>
  get<ReliabilityData>("/reliability", p);
export const getRisk = (p: { machine_id?: string; at?: string; target?: string }) =>
  get<RiskData>("/risk", p);
export const getRiskMetrics = () => get<RiskMetricsData>("/risk/metrics");
export const searchNotes = (p: Scope & { query: string }) => get<NotesData>("/notes/search", p);

// ---- Chat with the local model ----

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}
export interface ToolCall {
  name: string;
  args: Record<string, unknown> | string;
  status: string;
  missing: string | null;
}
export interface ChatResult {
  answer: string;
  citations: Citation[];
  citation_count: number;
  cited_event_ids: number[];
  unsupported_cited_ids: number[];
  tool_calls: ToolCall[];
  model: string;
  rounds: number;
}

/** POST /api/chat. A non-2xx answer throws with the envelope's `missing` text (503 when the
 * local model is not reachable) or the validation messages. */
export async function postChat(messages: ChatMessage[]): Promise<ChatResult> {
  const res = await fetch("/api/chat", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages }),
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = Array.isArray(body?.detail)
      ? body.detail.map((d: { msg: string }) => d.msg).join("; ")
      : null;
    throw new Error(body?.missing ?? detail ?? `${res.status} ${res.statusText}`);
  }
  return body as ChatResult;
}

// ---- Stage 3: session, approved actions, audit ----

export interface DemoUser {
  user_id: string;
  display_name: string;
  role: string;
  source: string;
}
export type ActionName = "work_order" | "quality_hold" | "follow_up";
export interface CheckResult {
  name: string;
  level: "pass" | "warn" | "block";
  message: string;
  detail: Record<string, unknown>;
}
export interface Preview {
  action: string;
  args: Record<string, unknown>;
  summary: string;
  checks: CheckResult[];
  code: string | null;
  evidence: Record<string, unknown>[];
  blocked: boolean;
}
export interface Outcome {
  outcome: string;
  message: string;
  checks: CheckResult[];
  proposal_id: number | null;
  target_id: number | null;
  audit_id?: number | null;
}
export interface ProposalRow {
  proposal_id: number;
  action: ActionName;
  summary: string;
  status: "pending" | "approved" | "rejected";
  principal: string;
  on_behalf_of: string;
  channel: string;
  created_at: string;
  decided_by: string | null;
  decided_at: string | null;
  target_id: number | null;
}
export interface EvidenceLink {
  event_key: string;
  event_id_at_link: number | null;
  current_event_id: number | null;
  present: boolean;
  line_id: string | null;
  machine_id: string | null;
  start_ts: string | null;
  duration_s: number | null;
  event_type: string | null;
  reason_code: string | null;
  alarm_code: string | null;
}
export interface LinkedNote {
  event_key: string;
  event_id: number | null;
  text: string;
  source: "core.note" | "demo.injected_note";
  translation: string | null;
  translation_model: string | null;
}
export interface ProposalDetail extends ProposalRow {
  args: Record<string, unknown>;
  checks: CheckResult[];
  warnings: CheckResult[];
  evidence: EvidenceLink[];
  notes: LinkedNote[];
  decision_note: string | null;
}
export interface AuditRow {
  audit_id: number;
  at: string;
  event: string;
  action: string | null;
  proposal_id: number | null;
  principal: string;
  on_behalf_of: string | null;
  channel: string | null;
  outcome: string;
  checks: CheckResult[] | null;
  detail: string | null;
}

/** A plain JSON call with the session cookie. Returns the status with the parsed body; it never
 * throws on a non-2xx answer, because a refusal's body is what the person needs to read. */
async function call<T>(method: string, path: string, body?: unknown) {
  const res = await fetch(`/api${path}`, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = (await res.json().catch(() => null)) as T | null;
  return { ok: res.ok, status: res.status, data };
}

/** Normalises any non-2xx body (an Outcome, a FastAPI `detail`, or nothing) to an Outcome. */
function asOutcome(r: { ok: boolean; status: number; data: unknown }): Outcome {
  const d = r.data as Partial<Outcome> & { detail?: unknown };
  if (d && typeof d.outcome === "string") return { checks: [], proposal_id: null, target_id: null, ...d } as Outcome;
  const detail = Array.isArray(d?.detail)
    ? d.detail.map((x: { msg?: string }) => x.msg).join("; ")
    : typeof d?.detail === "string"
      ? d.detail
      : `HTTP ${r.status}`;
  return { outcome: "refused", message: detail, checks: [], proposal_id: null, target_id: null };
}

async function list<T>(path: string): Promise<T> {
  const r = await call<T>("GET", path);
  if (!r.ok || r.data === null) throw new Error(`${r.status} for /api${path}`);
  return r.data;
}

export const getUsers = () => list<DemoUser[]>("/users");
export const getSession = () => list<{ user: DemoUser | null }>("/session");
export async function startSession(user_id: string) {
  const r = await call<{ user: DemoUser }>("POST", "/session", { user_id });
  if (!r.ok || !r.data) throw new Error(`Could not sign in (${r.status})`);
  return r.data.user;
}
export const endSession = () => call("DELETE", "/session");

export async function previewAction(action: ActionName, args: Record<string, unknown>) {
  const r = await call<Preview>("POST", `/actions/${action}/preview`, args);
  if (r.data && "checks" in r.data) return r.data;
  throw new Error(asOutcome(r).message);
}
export async function proposeAction(action: ActionName, args: Record<string, unknown>, code: string | null) {
  return asOutcome(await call("POST", `/actions/${action}/propose`, { args, code }));
}

export const getProposals = (status?: string) =>
  list<ProposalRow[]>(`/proposals${status ? `?status=${encodeURIComponent(status)}` : ""}`);
export const getProposal = (id: number | string) => list<ProposalDetail>(`/proposals/${id}`);
export const approveProposal = async (id: number, note = "") =>
  asOutcome(await call("POST", `/proposals/${id}/approve`, { note }));
export const rejectProposal = async (id: number, note = "") =>
  asOutcome(await call("POST", `/proposals/${id}/reject`, { note }));

export type ActionKind = "work_orders" | "quality_holds" | "follow_ups";
export const getActions = (kind: ActionKind) => list<Record<string, unknown>[]>(`/actions/${kind}`);
export const changeStatus = async (kind: ActionKind, id: number, verb: "close" | "release" | "complete") =>
  asOutcome(await call("POST", `/actions/${kind}/${id}/${verb}`));

export const getAudit = (proposalId?: number) =>
  list<AuditRow[]>(`/audit${proposalId ? `?proposal_id=${proposalId}` : ""}`);
