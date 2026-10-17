"""STEP_UP queue: a valid payment over the limit waits for the human.

Approve → the mandate is re-verified and a pass is issued for exactly the proposed payment.
Deny → BLOCK. An approval expires with its mandate and can be resolved only once.
"""

import sqlite3
from datetime import datetime

from app import db, events
from app.clock import parse_iso, to_iso
from app.config import Settings
from app.mandate import verify_mandate
from app.models import CheckResult, Decision, PendingApproval
from app.passes import issue_pass
from app.policy import outcome_of


class ApprovalError(Exception):
    def __init__(self, status: int, error: str, detail: str) -> None:
        super().__init__(f"{status} {error}: {detail}")
        self.status, self.error, self.detail = status, error, detail


def list_pending(conn: sqlite3.Connection, now: datetime) -> list[PendingApproval]:
    out: list[PendingApproval] = []
    for row in db.pending_approvals(conn):
        if now >= parse_iso(row["expires_at"]):
            continue
        d = Decision.model_validate_json(row["body"])
        out.append(PendingApproval(
            decision_id=d.decision_id, session_id=d.session_id, mandate_id=d.mandate_id or "",
            invoice_id=d.proposal.invoice_id, vendor_id=d.proposal.vendor_id, payee_account=d.proposal.payee_account,
            amount_paise=d.proposal.amount_paise, max_amount_paise=row["limit_paise"],
            requested_at=row["requested_at"], expires_at=row["expires_at"],
        ))
    return out


def resolve(conn: sqlite3.Connection, *, decision_id: str, approve: bool, settings: Settings, now: datetime) -> Decision:
    row = db.get_approval(conn, decision_id)
    if row is None:
        raise ApprovalError(404, "not_found", f"no approval request for {decision_id}")
    if row["status"] != "pending":
        raise ApprovalError(409, "already_resolved", f"approval is {row['status']}")
    ts = to_iso(now)
    if now >= parse_iso(row["expires_at"]):
        db.resolve_approval(conn, decision_id, "expired", ts)
        raise ApprovalError(409, "approval_expired", f"expired with its mandate at {row['expires_at']}")

    decision = db.get_decision(conn, decision_id)
    if decision is None or decision.outcome != "STEP_UP" or decision.mandate_id is None:
        raise ApprovalError(409, "not_approvable", "decision is not a pending step-up")
    mandate = db.get_mandate(conn, decision.mandate_id)
    amount, limit = decision.proposal.amount_paise, row["limit_paise"]

    if approve:
        verdict = verify_mandate(mandate, key=settings.mandate_key, now=now) if mandate else None
        if verdict is None or not verdict.ok:
            raise ApprovalError(409, "mandate_invalid", verdict.detail if verdict else "mandate not found")
        principal = mandate.principal if mandate else "the principal"
        limit_check = CheckResult(check="amount_within_limit", status="pass", detail=f"{amount} > {limit}; approved by {principal}")
    else:
        limit_check = CheckResult(check="amount_within_limit", status="fail", detail=f"{amount} > {limit}; denied by the principal")

    checks = [limit_check if c.check == "amount_within_limit" else c for c in decision.checks]
    # A denial is final. An approval only clears the limit, so every other check must still pass.
    outcome = outcome_of(checks) if approve else "BLOCK"
    if approve and outcome != "ALLOW":
        raise ApprovalError(409, "not_approvable", "other checks did not pass")
    resolved = decision.model_copy(update={"checks": checks, "outcome": outcome})
    if outcome == "ALLOW":
        resolved = resolved.model_copy(update={"one_pass": issue_pass(resolved, key=settings.pass_key, now=now, ttl_seconds=settings.pass_ttl_seconds)})

    with db.transaction(conn):
        if not db.resolve_approval(conn, decision_id, "approved" if approve else "denied", ts):
            raise ApprovalError(409, "already_resolved", "approval was resolved concurrently")
        db.update_decision(conn, resolved)
        if resolved.one_pass is not None:
            db.insert_pass(conn, resolved.one_pass, ts)
        events.emit(conn, "decision", resolved.session_id, {
            "decision_id": decision_id, "outcome": resolved.outcome, "mode": resolved.mode,
            "failed": [c.check for c in checks if c.status == "fail"], "via": "approval",
        }, ts)
    return resolved
