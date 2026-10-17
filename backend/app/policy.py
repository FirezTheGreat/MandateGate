"""The decision engine: decide(proposal, ctx) -> Decision (CLAUDE.md §6).

Pure and deterministic: no I/O, no LLM, no clock reads (time comes in ctx). Every check runs
and is reported, in CHECK_ORDER. A check that raises fails closed on its own; it can never
turn into a pass. The route issues the pass; this module never does.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.clock import to_iso
from app.delegation import CaveatError, EvalContext, amount_limit, evaluate, verify_chain
from app.mandate import verify_mandate
from app.models import (
    CHECK_ORDER,
    CheckName,
    CheckResult,
    Decision,
    GateMode,
    Mandate,
    Outcome,
    PaymentProposal,
    ProposalSummary,
    Session,
    ValueRecord,
)
from app.provenance import describe, matches, normalize

PAYEE_FIELD = "bank.account_number"  # the payee must be the vendor's registered bank account
AMOUNT_FIELD = "amount_due_paise"
PROVENANCE_CHECKS: tuple[CheckName, ...] = ("payee_provenance", "amount_provenance")


@dataclass(frozen=True)
class PolicyContext:
    """Everything decide() needs, pre-loaded by the caller."""

    decision_id: str
    now: datetime
    mode: GateMode
    mandate: Mandate | None  # loaded by the token's mandate_id; None if not found
    session: Session | None  # None if the proposal names an unknown session
    records: tuple[ValueRecord, ...]  # every value the broker recorded in this session
    mandate_key: str
    root_key: str


def _pass(name: CheckName, detail: str, **kw: object) -> CheckResult:
    return CheckResult(check=name, status="pass", detail=detail, **kw)  # type: ignore[arg-type]


def _fail(name: CheckName, detail: str, **kw: object) -> CheckResult:
    return CheckResult(check=name, status="fail", detail=detail, **kw)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- the six checks


def _mandate_valid(p: PaymentProposal, ctx: PolicyContext) -> CheckResult:
    name: CheckName = "mandate_valid"
    m = ctx.mandate
    if m is None:
        return _fail(name, f"mandate {p.token.mandate_id} not found")
    verdict = verify_mandate(m, key=ctx.mandate_key, now=ctx.now)
    if not verdict.ok:
        return _fail(name, verdict.detail)
    if ctx.session is None:
        return _fail(name, f"unknown session {p.session_id}")
    if ctx.session.mandate_id != m.mandate_id:
        return _fail(name, f"session {p.session_id} belongs to {ctx.session.mandate_id}, not {m.mandate_id}")
    return _pass(name, verdict.detail)


def _delegation_chain(p: PaymentProposal, ctx: PolicyContext) -> CheckResult:
    name: CheckName = "delegation_chain"
    chain = verify_chain(p.token, root_key=ctx.root_key)
    if not chain.ok:
        return _fail(name, chain.detail)
    if ctx.mandate is not None and p.token.mandate_id != ctx.mandate.mandate_id:
        return _fail(name, "token belongs to another mandate")
    held = evaluate(p.token.caveats, EvalContext(agent=p.agent_id, tool="propose_payment", invoice_id=p.invoice_id, now=ctx.now))
    if not held.ok:
        return _fail(name, held.detail)
    return _pass(name, f"{chain.detail}; {held.detail}")


def _invoice_matches_mandate(p: PaymentProposal, ctx: PolicyContext) -> CheckResult:
    name: CheckName = "invoice_matches_mandate"
    if ctx.mandate is None:
        return _fail(name, "no mandate to compare against")
    c = ctx.mandate.constraints
    if (p.invoice_id, p.vendor_id, p.currency) != (c.invoice_id, c.vendor_id, c.currency):
        return _fail(name, f"proposal {p.invoice_id} / {p.vendor_id} / {p.currency} ≠ mandate {c.invoice_id} / {c.vendor_id} / {c.currency}")
    return _pass(name, f"{p.invoice_id} / {p.vendor_id}")


def registered_payee_records(records: tuple[ValueRecord, ...] | list[ValueRecord], payee: str, vendor: str) -> list[ValueRecord]:
    """Trusted vendor-registry bank-account records for `vendor` that equal `payee` after normalisation.
    The payee passes only if one of them also equals it exactly (raw). Shared with the tracer."""
    n = normalize(payee)
    return [
        r for r in records
        if r.source_type == "vendor_registry" and r.source_ref == f"vendor:{vendor}" and r.field_hint == PAYEE_FIELD
        and r.trust == "trusted" and r.normalized == n
    ]


def amount_due_values(records: tuple[ValueRecord, ...] | list[ValueRecord], invoice: str) -> list[int]:
    """Trusted amount_due_paise values recorded from the invoice DB for `invoice`. Shared with the tracer."""
    return [
        int(r.raw) for r in records
        if r.source_type == "invoice_db" and r.source_ref == f"invoice:{invoice}" and r.field_hint == AMOUNT_FIELD
        and r.trust == "trusted" and r.raw.isdigit()
    ]


def _payee_provenance(p: PaymentProposal, ctx: PolicyContext) -> CheckResult:
    name: CheckName = "payee_provenance"
    if ctx.mandate is None:
        return _fail(name, "no mandate: required payee source unknown")
    vendor = ctx.mandate.constraints.vendor_id
    required = f"vendor_registry:{vendor}"
    seen = matches(ctx.records, p.payee_account)
    registered = registered_payee_records(seen, p.payee_account, vendor)
    found = describe(seen)
    if any(r.raw == p.payee_account for r in registered):
        return _pass(name, f"matches vendor:{vendor} {PAYEE_FIELD}", required=required, found=found)
    if registered:
        return _fail(name, f"matches vendor:{vendor}'s account only after reformatting; propose it exactly as registered", required=required, found=found)
    if not seen:
        return _fail(name, "unknown origin: payee appears in no tool output this session", required=required, found=[])
    return _fail(name, f"payee is not vendor:{vendor}'s registered account; seen only in {', '.join(found)}", required=required, found=found)


def _amount_provenance(p: PaymentProposal, ctx: PolicyContext) -> CheckResult:
    name: CheckName = "amount_provenance"
    if ctx.mandate is None:
        return _fail(name, "no mandate: invoice unknown")
    invoice = ctx.mandate.constraints.invoice_id
    required = f"invoice_db:{invoice}"
    due = amount_due_values(ctx.records, invoice)
    if not due:
        return _fail(name, f"invoice {invoice} was not looked up this session; the amount has no trusted source", required=required, found=[])
    if p.amount_paise in due:
        return _pass(name, f"invoice:{invoice}")
    found = describe(matches(ctx.records, str(p.amount_paise), contained=False))
    origin = f"seen only in {', '.join(found)}" if found else "unknown origin"
    return _fail(name, f"{p.amount_paise} ≠ {due[0]} due on invoice:{invoice} ({origin})", required=required, found=found)


def effective_limit(mandate_max_paise: int, caveats: list[str]) -> int:
    """min(mandate cap, tightest token cap). Raises CaveatError on malformed caveats."""
    token_cap = amount_limit(caveats)
    return mandate_max_paise if token_cap is None else min(mandate_max_paise, token_cap)


def _amount_within_limit(p: PaymentProposal, ctx: PolicyContext) -> CheckResult:
    name: CheckName = "amount_within_limit"
    if ctx.mandate is None:
        return _fail(name, "no mandate: limit unknown")
    try:
        limit = effective_limit(ctx.mandate.constraints.max_amount_paise, p.token.caveats)
    except CaveatError:
        return _fail(name, "token caveats unreadable; limit unknown")
    if p.amount_paise <= limit:
        return _pass(name, f"{p.amount_paise} <= {limit}")
    return _fail(name, f"{p.amount_paise} > {limit} (limit = min of mandate and token caps); needs human approval")


CHECKS: dict[CheckName, Callable[[PaymentProposal, PolicyContext], CheckResult]] = {
    "mandate_valid": _mandate_valid,
    "delegation_chain": _delegation_chain,
    "invoice_matches_mandate": _invoice_matches_mandate,
    "payee_provenance": _payee_provenance,
    "amount_provenance": _amount_provenance,
    "amount_within_limit": _amount_within_limit,
}


# --------------------------------------------------------------------------- decide


def _run(name: CheckName, p: PaymentProposal, ctx: PolicyContext) -> CheckResult:
    if ctx.mode == "baseline" and name in PROVENANCE_CHECKS:
        return CheckResult(check=name, status="skipped", detail="skipped in baseline mode (no provenance checks)")
    try:
        result = CHECKS[name](p, ctx)
    except Exception as e:  # fail closed: a broken check is a failed check
        return _fail(name, f"could not evaluate ({type(e).__name__}); failing closed")
    if result.check != name:
        return _fail(name, "check returned a result for another check; failing closed")
    return result


def outcome_of(checks: list[CheckResult]) -> Outcome:
    """Any of checks 1–5 failed → BLOCK; only the limit failed → STEP_UP; else ALLOW.
    A malformed check list is BLOCK."""
    if [c.check for c in checks] != list(CHECK_ORDER):
        return "BLOCK"
    if any(c.status == "fail" for c in checks[:5]):
        return "BLOCK"
    if checks[5].status != "pass":
        return "STEP_UP" if checks[5].status == "fail" else "BLOCK"
    return "ALLOW"


def summarize(p: PaymentProposal) -> ProposalSummary:
    return ProposalSummary(**p.model_dump(exclude={"session_id", "token"}))


def decide(p: PaymentProposal, ctx: PolicyContext) -> Decision:
    checks = [_run(name, p, ctx) for name in CHECK_ORDER]
    return Decision(
        decision_id=ctx.decision_id,
        session_id=p.session_id,
        mandate_id=ctx.mandate.mandate_id if ctx.mandate else None,
        mode=ctx.mode,
        created_at=to_iso(ctx.now),
        proposal=summarize(p),
        outcome=outcome_of(checks),
        checks=checks,
        one_pass=None,
        trace_available=True,  # GET /trace/{decision_id} rebuilds it from the session's records
    )


def fail_closed(p: PaymentProposal, *, decision_id: str, now: datetime, mode: GateMode, reason: str) -> Decision:
    """The decision returned when anything around decide() breaks: BLOCK, every check failed."""
    return Decision(
        decision_id=decision_id,
        session_id=p.session_id,
        mandate_id=None,
        mode=mode,
        created_at=to_iso(now),
        proposal=summarize(p),
        outcome="BLOCK",
        checks=[_fail(name, reason) for name in CHECK_ORDER],
        one_pass=None,
        trace_available=True,
    )
