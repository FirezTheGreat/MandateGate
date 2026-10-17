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

export interface CheckResult {
  check: CheckName;
  passed: boolean;
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
  outcome: Outcome;
  checks: CheckResult[];
  pass: OnePass | null;
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
  pass: OnePass | null;
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

export type TraceStatus = "good" | "bad" | "neutral";

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

export interface TraceGraph {
  decision_id: string;
  nodes: TraceNode[];
  edges: TraceEdge[];
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

export interface ErrorResponse {
  error: string;
  detail: string;
}
