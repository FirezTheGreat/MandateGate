// Hand-written mirror of backend/app/models.py. Keep in sync (CLAUDE.md §13–14).
// Money is integer paise. Timestamps are ISO-8601 UTC strings.

export type Outcome = "ALLOW" | "BLOCK" | "STEP_UP";
export type SourceType = "vendor_registry" | "invoice_db" | "email" | "web" | "user";
export type Trust = "trusted" | "untrusted";
export type GateMode = "gated" | "baseline";
export type Currency = "INR";
export type ToolName = "list_inbox" | "read_email" | "get_invoice" | "get_vendor";
export type CheckName =
  | "mandate_valid"
  | "delegation_chain"
  | "invoice_matches_mandate"
  | "payee_provenance"
  | "amount_provenance"
  | "amount_within_limit";
export type EventType =
  | "tool_call"
  | "value_recorded"
  | "proposal"
  | "decision"
  | "escalation_attempt"
  | "suspicious_input"
  | "payment";
/** "skipped": the check did not run (baseline mode skips payee/amount provenance). */
export type CheckStatus = "pass" | "fail" | "skipped";
export type AgentMode = "llm" | "scripted";

/** Report order == evaluation order. Decisions list checks in exactly this order. */
export const CHECK_ORDER: readonly CheckName[] = [
  "mandate_valid",
  "delegation_chain",
  "invoice_matches_mandate",
  "payee_provenance",
  "amount_provenance",
  "amount_within_limit",
];

/** Integer paise. ₹4,850 = 485000. Never a float. */
export type Paise = number;

// --- mandate

export interface MandateConstraints {
  invoice_id: string;
  vendor_id: string;
  max_amount_paise: Paise;
  currency: Currency;
  payee_source: SourceType;
}

export interface Mandate {
  mandate_id: string;
  principal: string;
  action: "pay_invoice";
  constraints: MandateConstraints;
  created_at: string;
  expires_at: string;
  signature: string;
}

export interface MandateCreateRequest {
  principal: string;
  constraints: MandateConstraints;
  ttl_seconds?: number;
}

// --- delegation

export interface DelegationToken {
  token_id: string;
  mandate_id: string;
  caveats: string[];
  parent_token_id: string | null;
  sig: string;
}

export interface MandateCreated {
  mandate: Mandate;
  token: DelegationToken;
}

export interface DelegateRequest {
  token: DelegationToken;
  caveats: string[];
}

// --- sessions

/** POST /sessions: one agent run, bound to one mandate. `scenario` picks the demo inbox. */
export interface SessionCreateRequest {
  mandate_id: string;
  scenario?: string | null; // ^[a-z0-9_]{1,64}$
}

export interface Session {
  session_id: string;
  mandate_id: string;
  scenario: string | null;
  mode: GateMode;
  created_at: string;
}

// --- broker / tools

export interface ToolInfo {
  name: ToolName;
  description: string;
  args: Record<string, string>;
  source_type: SourceType;
}

export interface ToolCallRequest {
  session_id: string;
  agent_id: string;
  token: DelegationToken;
  args?: Record<string, unknown>;
}

export interface ToolCallResult {
  tool_call_id: string;
  session_id: string;
  tool: ToolName;
  result: unknown;
  values_recorded: number;
}

export interface ValueRecord {
  value_id: string;
  session_id: string;
  raw: string;
  normalized: string;
  field_hint: string;
  source_type: SourceType;
  source_ref: string;
  trust: Trust;
  tool_call_id: string;
  agent_id: string;
  ts: string;
}

// --- proposals & decisions

export interface PaymentProposal {
  session_id: string;
  token: DelegationToken;
  agent_id: string;
  invoice_id: string;
  vendor_id: string;
  payee_account: string;
  amount_paise: Paise;
  currency: Currency;
  memo?: string;
}

/** The proposal as recorded on a Decision (no delegation token: it is a bearer credential). */
export interface ProposalSummary {
  agent_id: string;
  invoice_id: string;
  vendor_id: string;
  payee_account: string;
  amount_paise: Paise;
  currency: Currency;
  memo: string;
}

export interface CheckResult {
  check: CheckName;
  status: CheckStatus;
  detail?: string | null;
  required?: string | null;
  found?: string[] | null;
}

export interface OnePass {
  pass_id: string;
  decision_id: string;
  mandate_id: string;
  invoice_id: string;
  payee_account: string;
  amount_paise: Paise;
  currency: Currency;
  nonce: string;
  exp: string;
  sig: string;
}

export interface Decision {
  decision_id: string;
  session_id: string;
  mandate_id: string | null;
  mode: GateMode;
  created_at: string;
  proposal: ProposalSummary;
  outcome: Outcome;
  checks: CheckResult[]; // always all six, in CHECK_ORDER
  one_pass: OnePass | null;
  trace_available: boolean;
}

export interface PendingApproval {
  decision_id: string;
  session_id: string;
  mandate_id: string;
  invoice_id: string;
  vendor_id: string;
  payee_account: string;
  amount_paise: Paise;
  max_amount_paise: Paise;
  requested_at: string;
  expires_at: string;
}

export interface ApprovalRequest {
  approve: boolean;
}

// --- payment service

export interface Payment {
  invoice_id: string;
  payee_account: string;
  amount_paise: Paise;
  currency: Currency;
}

export interface PayRequest {
  one_pass: OnePass | null;
  payment: Payment;
}

export interface Receipt {
  receipt_id: string;
  pass_id: string;
  decision_id: string;
  invoice_id: string;
  payee_account: string;
  amount_paise: Paise;
  currency: Currency;
  paid_at: string;
}

// --- events & trace

export interface GateEvent {
  event_id: string;
  seq: number;
  type: EventType;
  session_id: string | null;
  ts: string;
  data: Record<string, unknown>;
}

export type TraceStatus = "good" | "bad" | "neutral" | "warn"; // warn = waiting for the human (STEP_UP)

export interface TraceNodeData {
  label: string;
  status: TraceStatus;
  trust?: Trust | null;
  ref?: string | null;
  detail?: string | null;
  [key: string]: unknown; // React Flow requires node data to be an indexable record
}

export interface TraceNode {
  id: string;
  type: "source" | "tool_call" | "proposal" | "decision";
  data: TraceNodeData;
  position: { x: number; y: number };
}

export interface TraceEdgeData {
  status: TraceStatus;
  field?: string | null;
  value?: string | null;
  [key: string]: unknown;
}

export interface TraceEdge {
  id: string;
  source: string;
  target: string;
  data: TraceEdgeData;
}

/** Where one critical proposal value appeared. */
export interface TraceField {
  field: "payee_account" | "amount_paise";
  value: string;
  status: "good" | "bad"; // good = traces to the trusted source the policy requires
  sources: string[]; // e.g. ["email:1842 (untrusted)"]
}

export interface TraceGraph {
  decision_id: string;
  nodes: TraceNode[];
  edges: TraceEdge[];
  fields: TraceField[];
}

/** Payment service → gate (signed). Arrives on the feed as `payment` event data. */
export interface PaymentEventReport {
  status: "paid" | "refused";
  sent_at: string;
  receipt?: Receipt | null;
  error?: string | null; // missing_pass | bad_signature | expired | field_mismatch | replay
  detail?: string | null;
  pass_id?: string | null;
  decision_id?: string | null;
  payee_account?: string | null;
  amount_paise?: Paise | null;
}

// --- admin & errors

export interface ModeRequest {
  mode: GateMode;
}

export interface ModeState {
  mode: GateMode;
}

export interface OkResponse {
  ok: boolean;
  detail?: string | null;
}

export interface RunScenarioRequest {
  scenario: string; // ^[a-z0-9_]{1,64}$
  agent?: AgentMode;
}

export interface RunScenarioStarted {
  session_id: string;
  scenario: string;
  mode: GateMode;
  agent: AgentMode;
  agent_label: string; // "AI agent (gemini-3.8-flash)" or "Simulated fooled agent (scripted)": always shown
}

// --- attack suite results (GET /attacks/results)

export interface AttackCaseResult {
  id: string;
  category: string;
  scenario: string | null;
  mode: GateMode;
  expected: Outcome;
  outcomes: Outcome[];
  attacker_paid_runs: number;
  runs: number;
}

export interface AttackResults {
  generated_at: string;
  total_cases: number;
  baseline_asr: number; // rate 0..1
  gated_asr: number;
  benign_fpr: number;
  cases: AttackCaseResult[];
}

export interface ErrorResponse {
  error: string;
  detail: string;
}
