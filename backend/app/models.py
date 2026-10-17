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
ToolName = Literal["list_inbox", "read_email", "get_invoice", "get_vendor", "fetch_page"]
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

# Integer paise only. strict=True rejects 4850.0 and "485000". Bounded (Rs. 10 lakh crore) so no
# amount can overflow SQLite's 64-bit INTEGER or the caveat grammar's 16 digits.
MAX_PAISE = 10**15
Paise = Annotated[int, Field(strict=True, ge=0, le=MAX_PAISE)]

# Bounded strings on everything that comes in: sizes, not judgement. A strange but short value
# still reaches the decision engine, which records a BLOCK the dashboard can show.
Ident = Annotated[str, Field(min_length=1, max_length=64)]
Account = Annotated[str, Field(min_length=1, max_length=128)]
Hex = Annotated[str, Field(max_length=128)]
MAX_CAVEATS = 64  # longest delegation chain the gate verifies
Caveat = Annotated[str, Field(max_length=256)]
# What a human may authorise must be expressible as a caveat (`invoice_id = X`) and as broker args.
InvoiceId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")]
VendorId = Annotated[str, Field(pattern=r"^[a-z0-9_]{1,32}$")]
Principal = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.@-]{1,64}$")]

# Scenario names reach file paths and subprocess arguments, hence the strict pattern.
ScenarioName = Annotated[str, Field(pattern=r"^[a-z0-9_]{1,64}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- mandate


class MandateConstraints(Contract):
    invoice_id: InvoiceId
    vendor_id: VendorId
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

    principal: Principal
    constraints: MandateConstraints
    ttl_seconds: int = Field(default=3600, strict=True, ge=60, le=86400)


# --------------------------------------------------------------------------- delegation


class DelegationToken(Contract):
    token_id: Ident
    mandate_id: Ident
    caveats: list[Caveat] = Field(max_length=MAX_CAVEATS)
    parent_token_id: Ident | None = None
    sig: Hex  # hex; sig0 = HMAC(ROOT_KEY, mandate_id), sig_i = HMAC(sig_{i-1}, caveat_i)


class MandateCreated(Contract):
    """Response of POST /mandates: the signed mandate plus its root delegation token."""

    mandate: Mandate
    token: DelegationToken


class DelegateRequest(Contract):
    """POST /delegate: append caveats to a token (attenuation only ever narrows)."""

    token: DelegationToken
    caveats: list[Caveat] = Field(min_length=1, max_length=MAX_CAVEATS)


# --------------------------------------------------------------------------- sessions


class SessionCreateRequest(Contract):
    """POST /sessions: one agent run, bound to one mandate. `scenario` picks the demo inbox."""

    mandate_id: Ident
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

    session_id: Ident
    agent_id: Ident
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

    session_id: Ident
    token: DelegationToken
    agent_id: Ident
    invoice_id: Ident
    vendor_id: Ident
    payee_account: Account
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

    pass_id: Ident
    decision_id: Ident
    mandate_id: Ident
    invoice_id: Ident
    payee_account: Account
    amount_paise: Paise
    currency: Currency
    nonce: Hex  # 32 hex
    exp: Ident
    sig: Hex  # hex HMAC(PASS_KEY, canonical(pass without sig))


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

    invoice_id: Ident
    payee_account: Account
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
    status: Literal["good", "bad", "neutral", "warn"]  # warn = waiting for the human (STEP_UP)
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
    status: Literal["good", "bad", "neutral", "warn"]  # warn = waiting for the human (STEP_UP)
    field: str | None = None  # critical field carried along this edge, e.g. "payee_account"
    value: str | None = None


class TraceEdge(Contract):
    """Shaped for React Flow: {id, source, target, data}."""

    id: str
    source: str
    target: str
    data: TraceEdgeData


class TraceField(Contract):
    """Where one critical proposal value appeared, e.g. payee_account EVE-777 → ["email:1842 (untrusted)"]."""

    field: Literal["payee_account", "amount_paise"]
    value: str
    status: Literal["good", "bad"]  # good = it traces to the trusted source the policy requires
    sources: list[str]


class TraceGraph(Contract):
    decision_id: str
    nodes: list[TraceNode]
    edges: list[TraceEdge]
    fields: list[TraceField] = Field(default_factory=list)


class PaymentEventReport(Contract):
    """Payment service → gate (POST /internal/payment-event), signed with header
    X-MandateGate-Signature = hex HMAC(PASS_KEY, canonical(body)). Display only, never decides."""

    status: Literal["paid", "refused"]
    sent_at: str
    receipt: "Receipt | None" = None  # when paid
    error: str | None = None  # when refused: missing_pass | bad_signature | expired | field_mismatch | replay
    detail: str | None = None
    pass_id: str | None = None
    decision_id: str | None = None
    payee_account: str | None = None
    amount_paise: Paise | None = None


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
    agent_label: str  # "AI agent (gemini-3.8-flash)" or "Simulated fooled agent (scripted)": always shown


# --------------------------------------------------------------------------- attack suite results


SuiteAgent = Literal["scripted", "llm", "protocol"]
# ALLOW / BLOCK / STEP_UP: the gate's first decision. PAID / REJECTED: the payment service's answer
# (payment-rail attacks). NO_PROPOSAL: the agent ended without proposing. ERROR: the run itself failed.
RunOutcome = Literal["ALLOW", "BLOCK", "STEP_UP", "PAID", "REJECTED", "NO_PROPOSAL", "ERROR"]


class SuiteRun(Contract):
    """One run of one case."""

    outcome: RunOutcome
    succeeded: bool  # the attack got what it wanted (money moved its way / a forged request was accepted)
    fooled: bool | None  # the agent proposed the attacker's value; None for benign and protocol cases
    false_positive: bool  # benign only: the gate blocked the legitimate payment
    payee_account: str | None = None  # what the agent proposed
    amount_paise: Paise | None = None
    invoice_id: str | None = None
    detail: str | None = None  # failed checks, payment-service error, or why the run failed


class AttackCaseResult(Contract):
    """One suite case, in one mode, for one agent kind."""

    id: str  # "A01"
    category: str  # "payee_swap_email", ..., "benign"
    title: str
    how: str
    kind: Literal["attack", "benign", "protocol"]
    scenario: str | None  # None for protocol-level cases (tamper, replay, bypass, escalation)
    agent: SuiteAgent
    mode: GateMode
    expected: str  # ALLOW / BLOCK / STEP_UP, or REJECTED for payment-rail attacks
    runs: list[SuiteRun]  # one per run (LLM cases run 3x)
    succeeded_runs: int
    fooled_runs: int
    correct_runs: int  # outcome == expected


class SuiteMetrics(Contract):
    """Headline numbers for one agent kind. Rates are 0..1 (rates, not money); None when not applicable."""

    agent: SuiteAgent
    label: str  # "Simulated fooled agent", "AI agent (gemini-3.8-flash)", "Protocol attacks (no agent)"
    baseline_asr: float | None  # attack success rate without MandateGate
    gated_asr: float | None  # attack success rate with MandateGate (target 0)
    benign_fpr: float | None  # legit payments wrongly blocked with MandateGate (target 0)
    fooled_rate: float | None  # how often the agent proposed the attacker's value
    attack_runs: int
    benign_runs: int
    error_runs: int


class AttackResults(Contract):
    """attacks/results.json, written by `make attacks`, served by GET /attacks/results."""

    generated_at: str
    model: str | None  # the LLM used for agent=llm runs, if any
    llm_generated_at: str | None  # when the AI-agent runs were made (kept from an earlier `make attacks LLM=1` if not re-run)
    total_cases: int
    total_runs: int
    metrics: list[SuiteMetrics]
    cases: list[AttackCaseResult]


class ErrorResponse(Contract):
    """Every gate/payment-service error body. Never contains stack traces."""

    error: str
    detail: str
