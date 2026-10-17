"""Shared data contracts (CLAUDE.md §6). Source of truth for every workstream.

Rules:
- Every model forbids unknown fields (`extra="forbid"`), so an agent cannot smuggle
  `source`/`trust`/`provenance` fields in. Rejections surface as 422.
- Money is integer paise, validated strictly (no floats, no numeric strings).
- Timestamps are ISO-8601 UTC strings. IDs are prefixed strings (`mdt_`, `tok_`, ...).

Changing anything here? Update `frontend/src/types.ts` and CLAUDE.md in the same commit.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- enums

Outcome = Literal["ALLOW", "BLOCK", "STEP_UP"]
SourceType = Literal["vendor_registry", "invoice_db", "email", "web", "user"]
Trust = Literal["trusted", "untrusted"]
GateMode = Literal["gated", "baseline"]
Currency = Literal["INR"]
ToolName = Literal["list_inbox", "read_email", "get_invoice", "get_vendor"]
CheckName = Literal[
    "mandate_valid",
    "delegation_chain",
    "invoice_matches_mandate",
    "payee_provenance",
    "amount_provenance",
    "amount_within_limit",
]
EventType = Literal[
    "tool_call",
    "value_recorded",
    "proposal",
    "decision",
    "escalation_attempt",
    "suspicious_input",
    "payment",
]
CheckStatus = Literal["pass", "fail", "skipped"]  # "skipped": not run (baseline mode skips checks 4–5)
AgentMode = Literal["llm", "scripted"]

# Report order == evaluation order (CLAUDE.md §6). Decisions list checks in exactly this order.
CHECK_ORDER: tuple[CheckName, ...] = (
    "mandate_valid",
    "delegation_chain",
    "invoice_matches_mandate",
    "payee_provenance",
    "amount_provenance",
    "amount_within_limit",
)

# Integer paise only. strict=True rejects 4850.0 and "485000".
Paise = Annotated[int, Field(strict=True, ge=0)]

# Scenario names reach file paths and subprocess arguments, hence the strict pattern.
ScenarioName = Annotated[str, Field(pattern=r"^[a-z0-9_]{1,64}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- mandate


class MandateConstraints(Contract):
    invoice_id: str
    vendor_id: str
    max_amount_paise: Paise
    currency: Currency = "INR"
    payee_source: SourceType = "vendor_registry"


class Mandate(Contract):
    mandate_id: str
    principal: str
    action: Literal["pay_invoice"] = "pay_invoice"
    constraints: MandateConstraints
    created_at: str
    expires_at: str
    signature: str  # hex HMAC(MANDATE_KEY, canonical(mandate without signature))


class MandateCreateRequest(Contract):
    """Dashboard form → POST /mandates."""

    principal: str
    constraints: MandateConstraints
    ttl_seconds: int = Field(default=3600, strict=True, ge=60, le=86400)


# --------------------------------------------------------------------------- delegation


class DelegationToken(Contract):
    token_id: str
    mandate_id: str
    caveats: list[str]
    parent_token_id: str | None = None
    sig: str  # hex; sig0 = HMAC(ROOT_KEY, mandate_id), sig_i = HMAC(sig_{i-1}, caveat_i)


class MandateCreated(Contract):
    """Response of POST /mandates: the signed mandate plus its root delegation token."""

    mandate: Mandate
    token: DelegationToken


class DelegateRequest(Contract):
    """POST /delegate: append caveats to a token (attenuation only ever narrows)."""

    token: DelegationToken
    caveats: list[str] = Field(min_length=1)


# --------------------------------------------------------------------------- sessions


class SessionCreateRequest(Contract):
    """POST /sessions: one agent run, bound to one mandate. `scenario` picks the demo inbox."""

    mandate_id: str
    scenario: ScenarioName | None = None


class Session(Contract):
    session_id: str
    mandate_id: str
    scenario: str | None
    mode: GateMode  # gate mode when the session started (each Decision records the mode it used)
    created_at: str


# --------------------------------------------------------------------------- broker / tools


class ToolInfo(Contract):
    name: ToolName
    description: str
    args: dict[str, str]  # arg name → type hint, e.g. {"email_id": "string"}
    source_type: SourceType


class ToolCallRequest(Contract):
    """POST /tools/{name}. Tool name comes from the path, never from the body."""

    session_id: str
    agent_id: str
    token: DelegationToken
    args: dict[str, Any] = Field(default_factory=dict)


class ToolCallResult(Contract):
    tool_call_id: str
    session_id: str
    tool: ToolName
    result: Any  # the tool's JSON output, returned to the agent as-is
    values_recorded: int


class ValueRecord(Contract):
    """One row of the gate's provenance store (SQLite `value_records`)."""

    value_id: str
    session_id: str
    raw: str
    normalized: str
    field_hint: str  # JSON path within the tool result, e.g. "bank.account_number"
    source_type: SourceType
    source_ref: str  # "vendor:acme", "invoice:INV-1048", "email:1842"
    trust: Trust
    tool_call_id: str
    agent_id: str
    ts: str


# --------------------------------------------------------------------------- proposals & decisions


class PaymentProposal(Contract):
    """Agent → gate (`propose_payment`). Extra fields such as `trusted` are rejected."""

    session_id: str
    token: DelegationToken
    agent_id: str
    invoice_id: str
    vendor_id: str
    payee_account: str
    amount_paise: Paise
    currency: Currency
    memo: str = Field(default="", max_length=2000)  # display only, never parsed


class ProposalSummary(Contract):
    """The proposal as recorded on a Decision. Omits the delegation token, which is a
    bearer credential and must never be echoed back through history/dashboard APIs."""

    agent_id: str
    invoice_id: str
    vendor_id: str
    payee_account: str
    amount_paise: Paise
    currency: Currency
    memo: str = ""


class CheckResult(Contract):
    check: CheckName
    status: CheckStatus
    detail: str | None = None
    required: str | None = None
    found: list[str] | None = None


class OnePass(Contract):
    """HMAC-sealed, single-use, short-lived pass bound to exact payment fields."""

    pass_id: str
    decision_id: str
    mandate_id: str
    invoice_id: str
    payee_account: str
    amount_paise: Paise
    currency: Currency
    nonce: str  # 32 hex
    exp: str
    sig: str  # hex HMAC(PASS_KEY, canonical(pass without sig))


class Decision(Contract):
    decision_id: str
    session_id: str
    mandate_id: str | None  # None when the proposal referenced no loadable mandate (→ BLOCK)
    mode: GateMode
    created_at: str
    proposal: ProposalSummary
    outcome: Outcome
    checks: list[CheckResult]  # always all six, in CHECK_ORDER
    one_pass: OnePass | None = None
    trace_available: bool


class PendingApproval(Contract):
    """A STEP_UP waiting for the human (GET /approvals)."""

    decision_id: str
    session_id: str
    mandate_id: str
    invoice_id: str
    vendor_id: str
    payee_account: str
    amount_paise: Paise
    max_amount_paise: Paise
    requested_at: str
    expires_at: str


class ApprovalRequest(Contract):
    approve: bool = Field(strict=True)


# --------------------------------------------------------------------------- payment service


class Payment(Contract):
    """The payment being executed. Must equal the pass fields exactly."""

    invoice_id: str
    payee_account: str
    amount_paise: Paise
    currency: Currency


class PayRequest(Contract):
    """POST /pay on the payment service. A missing pass → 401 missing_pass (not 422)."""

    one_pass: OnePass | None = None
    payment: Payment


class Receipt(Contract):
    """Returned by POST /pay; GET /ledger returns a list of these."""

    receipt_id: str
    pass_id: str
    decision_id: str
    invoice_id: str
    payee_account: str
    amount_paise: Paise
    currency: Currency
    paid_at: str


# --------------------------------------------------------------------------- events & trace


class Event(Contract):
    event_id: str
    seq: int
    type: EventType
    session_id: str | None = None
    ts: str
    data: dict[str, Any] = Field(default_factory=dict)


class Position(Contract):
    x: float
    y: float


class TraceNodeData(Contract):
    label: str
    status: Literal["good", "bad", "neutral"]
    trust: Trust | None = None
    ref: str | None = None  # e.g. "email:1842", "finance:read_email"
    detail: str | None = None


class TraceNode(Contract):
    """Shaped for React Flow: {id, type, data, position}."""

    id: str
    type: Literal["source", "tool_call", "proposal", "decision"]
    data: TraceNodeData
    position: Position


class TraceEdgeData(Contract):
    status: Literal["good", "bad", "neutral"]
    field: str | None = None  # critical field carried along this edge, e.g. "payee_account"
    value: str | None = None


class TraceEdge(Contract):
    """Shaped for React Flow: {id, source, target, data}."""

    id: str
    source: str
    target: str
    data: TraceEdgeData


class TraceGraph(Contract):
    decision_id: str
    nodes: list[TraceNode]
    edges: list[TraceEdge]


# --------------------------------------------------------------------------- admin & errors


class ModeRequest(Contract):
    mode: GateMode


class ModeState(Contract):
    mode: GateMode


class OkResponse(Contract):
    ok: bool
    detail: str | None = None


class RunScenarioRequest(Contract):
    """POST /admin/run-scenario. Runs in the gate's current mode (see /admin/mode).
    The name is passed to a subprocess, hence the strict pattern."""

    scenario: ScenarioName
    agent: AgentMode = "scripted"


class RunScenarioStarted(Contract):
    session_id: str
    scenario: str
    mode: GateMode
    agent: AgentMode


# --------------------------------------------------------------------------- attack suite results


class AttackCaseResult(Contract):
    id: str  # "A01"
    category: str  # "payee_swap_email", ..., "benign"
    scenario: str | None  # None for protocol-level cases (tamper, replay, bypass)
    mode: GateMode
    expected: Outcome
    outcomes: list[Outcome]  # one per run (LLM cases run 3x)
    attacker_paid_runs: int
    runs: int


class AttackResults(Contract):
    """attacks/results.json, served by GET /attacks/results."""

    generated_at: str
    total_cases: int
    baseline_asr: float  # attack success rate, 0..1 (a rate, not money)
    gated_asr: float
    benign_fpr: float
    cases: list[AttackCaseResult]


class ErrorResponse(Contract):
    """Every gate/payment-service error body. Never contains stack traces."""

    error: str
    detail: str
