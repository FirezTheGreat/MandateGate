"""POST /proposals (agent-facing name: propose_payment) → Decision.

Load context → policy.decide (pure) → on ALLOW issue a pass → persist decision, pass, approval
request and events in one transaction. Any exception anywhere → BLOCK without a pass
(CLAUDE.md §2.7): a pass is only returned if it was durably recorded first.
"""

import logging
import sqlite3
from datetime import datetime

from fastapi import APIRouter

from app import db, events, policy
from app.clock import to_iso, utc_now
from app.config import Settings
from app.crypto import new_id
from app.delegation import CaveatError, detect_escalation
from app.deps import ConnDep, ModeDep, SettingsDep
from app.models import Decision, PaymentProposal
from app.passes import issue_pass

router = APIRouter(tags=["proposals"])
log = logging.getLogger("mandategate.proposals")


@router.post("/proposals", response_model=Decision)
def submit_proposal(p: PaymentProposal, settings: SettingsDep, mode: ModeDep, conn: ConnDep) -> Decision:
    now = utc_now()
    decision_id = new_id("dec")
    try:
        ctx = policy.PolicyContext(
            decision_id=decision_id, now=now, mode=mode,
            mandate=db.get_mandate(conn, p.token.mandate_id),
            session=db.get_session(conn, p.session_id),
            records=tuple(db.session_values(conn, p.session_id)),
            mandate_key=settings.mandate_key, root_key=settings.root_key,
        )
        decision = policy.decide(p, ctx)
        if decision.outcome == "ALLOW":
            decision = decision.model_copy(update={"one_pass": issue_pass(decision, key=settings.pass_key, now=now, ttl_seconds=settings.pass_ttl_seconds)})
        _persist(conn, p, decision, ctx, settings, now)
        return decision
    except Exception:
        log.exception("proposal %s failed; returning BLOCK", decision_id)
        blocked = policy.fail_closed(p, decision_id=decision_id, now=now, mode=mode, reason="internal error; failing closed")
        try:
            with db.transaction(conn):
                db.insert_decision(conn, blocked)
                _emit_decision(conn, blocked, to_iso(now))
        except Exception:
            log.exception("could not record fail-closed decision %s", decision_id)
        return blocked


def _persist(conn: sqlite3.Connection, p: PaymentProposal, d: Decision, ctx: policy.PolicyContext, settings: Settings, now: datetime) -> None:
    ts = to_iso(now)
    try:
        escalations = detect_escalation(p.token.caveats)
    except CaveatError:
        escalations = []  # unparseable caveats already failed delegation_chain
    with db.transaction(conn):
        db.insert_decision(conn, d)
        if d.one_pass is not None:
            db.insert_pass(conn, d.one_pass, ts)
        if d.outcome == "STEP_UP" and ctx.mandate is not None:
            limit = policy.effective_limit(ctx.mandate.constraints.max_amount_paise, p.token.caveats)
            db.insert_approval(conn, decision_id=d.decision_id, limit_paise=limit, requested_at=ts, expires_at=ctx.mandate.expires_at)
        events.emit(conn, "proposal", p.session_id, {
            "agent_id": p.agent_id, "invoice_id": p.invoice_id, "vendor_id": p.vendor_id,
            "payee_account": p.payee_account, "amount_paise": p.amount_paise,
        }, ts)
        if escalations:
            events.emit(conn, "escalation_attempt", p.session_id, {
                "token_id": p.token.token_id, "mandate_id": p.token.mandate_id, "caveats": escalations,
            }, ts)
        _emit_decision(conn, d, ts)


def _emit_decision(conn: sqlite3.Connection, d: Decision, ts: str) -> None:
    data = {
        "decision_id": d.decision_id, "outcome": d.outcome, "mode": d.mode,
        "failed": [c.check for c in d.checks if c.status == "fail"],
    }
    if d.outcome == "STEP_UP":
        data["approval"] = "pending"  # the dashboard opens the ApprovalModal on this
    events.emit(conn, "decision", d.session_id, data, ts)
