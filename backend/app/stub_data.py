"""PHASE 0 ONLY: hard-coded example responses so the frontend can build against the API.

Every object is constructed through models.py, so this module also proves the contracts
validate. Delete each piece as the real implementation lands (Phases 1, 2, 4).
Signatures here are all zeros: they are not real and must never verify.
"""

import json

from app.config import FIXTURES_DIR
from app.models import (
    CheckResult,
    Decision,
    DelegationToken,
    Event,
    Mandate,
    MandateConstraints,
    OnePass,
    PendingApproval,
    Position,
    Receipt,
    ToolInfo,
    TraceEdge,
    TraceEdgeData,
    TraceGraph,
    TraceNode,
    TraceNodeData,
)

FAKE_SIG = "0" * 64
TS = "2026-10-17T09:00:00Z"

MANDATE = Mandate(
    mandate_id="mdt_example",
    principal="abhishek",
    action="pay_invoice",
    constraints=MandateConstraints(
        invoice_id="INV-1048",
        vendor_id="acme",
        max_amount_paise=500000,
        currency="INR",
        payee_source="vendor_registry",
    ),
    created_at=TS,
    expires_at="2026-10-17T10:00:00Z",
    signature=FAKE_SIG,
)

ROOT_TOKEN = DelegationToken(
    token_id="tok_root_example",
    mandate_id="mdt_example",
    caveats=[
        "agent in planner,finance",
        "tool in list_inbox,read_email,get_invoice,get_vendor,propose_payment",
        "max_amount_paise <= 500000",
    ],
    parent_token_id=None,
    sig=FAKE_SIG,
)

FINANCE_TOKEN = DelegationToken(
    token_id="tok_finance_example",
    mandate_id="mdt_example",
    caveats=[*ROOT_TOKEN.caveats, "agent = finance"],
    parent_token_id="tok_root_example",
    sig=FAKE_SIG,
)

TOOLS = [
    ToolInfo(name="list_inbox", description="List emails in the accounts-payable inbox.", args={}, source_type="email"),
    ToolInfo(name="read_email", description="Read one email by id.", args={"email_id": "string"}, source_type="email"),
    ToolInfo(
        name="get_invoice",
        description="Fetch an invoice from the invoice database.",
        args={"invoice_id": "string"},
        source_type="invoice_db",
    ),
    ToolInfo(
        name="get_vendor",
        description="Fetch a vendor record (incl. bank details) from the vendor registry.",
        args={"vendor_id": "string"},
        source_type="vendor_registry",
    ),
]

# --------------------------------------------------------------------------- decisions

# Matches the Decision example in CLAUDE.md §6 (hero attack, gated mode).
DEC_EXAMPLE = Decision(
    decision_id="dec_example",
    outcome="BLOCK",
    checks=[
        CheckResult(check="mandate_valid", passed=True, detail="signature ok, expires 2026-10-17T10:00:00Z"),
        CheckResult(check="delegation_chain", passed=True, detail="4 caveats verified, all hold for agent=finance"),
        CheckResult(check="invoice_matches_mandate", passed=True, detail="INV-1048 / acme"),
        CheckResult(check="amount_within_limit", passed=True, detail="485000 <= 500000"),
        CheckResult(
            check="payee_provenance",
            passed=False,
            required="vendor_registry:acme",
            found=["email:1842 (untrusted)"],
        ),
        CheckResult(check="amount_provenance", passed=True, detail="invoice:INV-1048"),
    ],
    pass_=None,
    trace_available=True,
)

EXAMPLE_PASS = OnePass(
    pass_id="pas_example",
    decision_id="dec_allow_example",
    mandate_id="mdt_example",
    invoice_id="INV-1048",
    payee_account="ACME-4410-2291",
    amount_paise=485000,
    currency="INR",
    nonce="0" * 32,
    exp="2026-10-17T09:02:00Z",
    sig=FAKE_SIG,
)

DEC_ALLOW_EXAMPLE = Decision(
    decision_id="dec_allow_example",
    outcome="ALLOW",
    checks=[
        CheckResult(check="mandate_valid", passed=True, detail="signature ok, expires 2026-10-17T10:00:00Z"),
        CheckResult(check="delegation_chain", passed=True, detail="4 caveats verified, all hold for agent=finance"),
        CheckResult(check="invoice_matches_mandate", passed=True, detail="INV-1048 / acme"),
        CheckResult(check="amount_within_limit", passed=True, detail="485000 <= 500000"),
        CheckResult(
            check="payee_provenance",
            passed=True,
            required="vendor_registry:acme",
            found=["vendor:acme (trusted)"],
        ),
        CheckResult(check="amount_provenance", passed=True, detail="invoice:INV-1048"),
    ],
    pass_=EXAMPLE_PASS,
    trace_available=True,
)

DEC_STEPUP_EXAMPLE = Decision(
    decision_id="dec_stepup_example",
    outcome="STEP_UP",
    checks=[
        CheckResult(check="mandate_valid", passed=True, detail="signature ok, expires 2026-10-17T10:00:00Z"),
        CheckResult(check="delegation_chain", passed=True, detail="4 caveats verified, all hold for agent=finance"),
        CheckResult(check="invoice_matches_mandate", passed=True, detail="INV-1052 / acme"),
        CheckResult(check="amount_within_limit", passed=False, detail="520000 > 500000, needs human approval"),
        CheckResult(
            check="payee_provenance",
            passed=True,
            required="vendor_registry:acme",
            found=["vendor:acme (trusted)"],
        ),
        CheckResult(check="amount_provenance", passed=True, detail="invoice:INV-1052"),
    ],
    pass_=None,
    trace_available=True,
)

DECISIONS = {d.decision_id: d for d in (DEC_EXAMPLE, DEC_ALLOW_EXAMPLE, DEC_STEPUP_EXAMPLE)}

PENDING_APPROVALS = [
    PendingApproval(
        decision_id="dec_stepup_example",
        session_id="ses_stepup_example",
        mandate_id="mdt_stepup_example",
        invoice_id="INV-1052",
        vendor_id="acme",
        payee_account="ACME-4410-2291",
        amount_paise=520000,
        max_amount_paise=500000,
        requested_at=TS,
        expires_at="2026-10-17T10:00:00Z",
    )
]

# --------------------------------------------------------------------------- ledger

LEDGER = [
    Receipt(
        receipt_id="rcp_example",
        pass_id="pas_example",
        decision_id="dec_allow_example",
        invoice_id="INV-1048",
        payee_account="ACME-4410-2291",
        amount_paise=485000,
        currency="INR",
        paid_at="2026-10-17T09:00:05Z",
    )
]

# --------------------------------------------------------------------------- events


def _ev(seq: int, type_: str, data: dict) -> Event:
    return Event(
        event_id=f"evt_example_{seq:02d}",
        seq=seq,
        type=type_,  # type: ignore[arg-type]
        session_id="ses_example",
        ts=f"2026-10-17T09:00:{seq:02d}Z",
        data=data,
    )


SESSION_EVENTS = [
    _ev(1, "tool_call", {"agent_id": "finance", "tool": "list_inbox", "args": {}}),
    _ev(2, "tool_call", {"agent_id": "finance", "tool": "read_email", "args": {"email_id": "1842"}}),
    _ev(3, "value_recorded", {"raw": "EVE-777", "source_ref": "email:1842", "trust": "untrusted"}),
    _ev(4, "tool_call", {"agent_id": "finance", "tool": "get_invoice", "args": {"invoice_id": "INV-1048"}}),
    _ev(5, "value_recorded", {"raw": "485000", "source_ref": "invoice:INV-1048", "trust": "trusted"}),
    _ev(6, "tool_call", {"agent_id": "finance", "tool": "get_vendor", "args": {"vendor_id": "acme"}}),
    _ev(7, "value_recorded", {"raw": "ACME-4410-2291", "source_ref": "vendor:acme", "trust": "trusted"}),
    _ev(8, "proposal", {"agent_id": "finance", "payee_account": "EVE-777", "amount_paise": 485000}),
    _ev(9, "decision", {"decision_id": "dec_example", "outcome": "BLOCK"}),
]

# --------------------------------------------------------------------------- trace


def _node(id_: str, type_: str, col: int, row: int, **data: object) -> TraceNode:
    return TraceNode(
        id=id_,
        type=type_,  # type: ignore[arg-type]
        data=TraceNodeData(**data),  # type: ignore[arg-type]
        position=Position(x=col * 280, y=row * 120),
    )


def _edge(source: str, target: str, status: str, field: str | None = None, value: str | None = None) -> TraceEdge:
    return TraceEdge(
        id=f"{source}->{target}",
        source=source,
        target=target,
        data=TraceEdgeData(status=status, field=field, value=value),  # type: ignore[arg-type]
    )


TRACE_EXAMPLE = TraceGraph(
    decision_id="dec_example",
    nodes=[
        _node("src_vendor_acme", "source", 0, 0, label="Vendor registry: acme", status="good", trust="trusted", ref="vendor:acme"),
        _node("src_invoice_1048", "source", 0, 1, label="Invoice DB: INV-1048", status="good", trust="trusted", ref="invoice:INV-1048"),
        _node("src_email_1842", "source", 0, 2, label="Email #1842", status="bad", trust="untrusted", ref="email:1842",
              detail="from accounts@acme-supp1ies.com"),
        _node("tc_get_vendor", "tool_call", 1, 0, label="finance: get_vendor", status="good", ref="finance:get_vendor"),
        _node("tc_get_invoice", "tool_call", 1, 1, label="finance: get_invoice", status="good", ref="finance:get_invoice"),
        _node("tc_read_email", "tool_call", 1, 2, label="finance: read_email", status="bad", ref="finance:read_email"),
        _node("proposal", "proposal", 2, 1, label="Proposal: EVE-777, 485000 paise", status="bad"),
        _node("decision", "decision", 3, 1, label="BLOCK", status="bad", detail="payee_provenance failed"),
    ],
    edges=[
        _edge("src_vendor_acme", "tc_get_vendor", "good"),
        _edge("src_invoice_1048", "tc_get_invoice", "good"),
        _edge("src_email_1842", "tc_read_email", "bad"),
        _edge("tc_read_email", "proposal", "bad", field="payee_account", value="EVE-777"),
        _edge("tc_get_invoice", "proposal", "good", field="amount_paise", value="485000"),
        _edge("proposal", "decision", "bad"),
    ],
)

TRACES = {"dec_example": TRACE_EXAMPLE}

# --------------------------------------------------------------------------- tool results (read from fixtures)


def _load(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def tool_result(name: str, args: dict) -> object | None:
    """Return fixture data for a tool call, or None if the args don't resolve."""
    if name == "list_inbox":
        emails = [_load(f"emails/{p.name}") for p in sorted((FIXTURES_DIR / "emails").glob("*.json"))]
        return [{k: e[k] for k in ("email_id", "from", "from_name", "subject", "received_at")} for e in emails]
    if name == "read_email":
        email_id = str(args.get("email_id", ""))
        if not email_id.isdigit():  # also blocks path traversal like "../vendors"
            return None
        path = FIXTURES_DIR / "emails" / f"{email_id}.json"
        return _load(f"emails/{email_id}.json") if path.is_file() else None
    if name == "get_invoice":
        return _load("invoices.json").get(str(args.get("invoice_id")))
    if name == "get_vendor":
        return _load("vendors.json").get(str(args.get("vendor_id")))
    return None
