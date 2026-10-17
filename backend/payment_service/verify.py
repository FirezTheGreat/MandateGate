"""Pass verification + nonce burn: the payment rail's only way to move money.

Order (CLAUDE.md §6): signature → expiry → exact field match → atomic nonce burn → ledger.
There is no bypass, debug flag, or "skip verification" path (CLAUDE.md §2.4).
"""

import sqlite3
from datetime import datetime

from app import db
from app.clock import parse_iso, to_iso
from app.crypto import new_id, verify
from app.models import PayRequest, Receipt
from app.passes import pass_payload

BOUND_FIELDS = ("invoice_id", "payee_account", "amount_paise", "currency")


class PayError(Exception):
    def __init__(self, status: int, error: str, detail: str) -> None:
        super().__init__(f"{status} {error}: {detail}")
        self.status, self.error, self.detail = status, error, detail


def verify_and_pay(conn: sqlite3.Connection, req: PayRequest, *, key: str, now: datetime) -> Receipt:
    p = req.one_pass
    if p is None:
        raise PayError(401, "missing_pass", "a one-time pass is required")

    if not verify(key, pass_payload(p), p.sig):
        raise PayError(401, "bad_signature", "pass signature invalid")

    try:
        exp = parse_iso(p.exp)
    except ValueError:
        raise PayError(401, "expired", "pass expiry unparseable") from None
    if now >= exp:
        raise PayError(401, "expired", f"pass expired at {p.exp}")

    # Exact equality, no normalisation: the payee must be byte-for-byte what the gate approved.
    mismatched = [f for f in BOUND_FIELDS if getattr(req.payment, f) != getattr(p, f)]
    if mismatched:
        raise PayError(403, "field_mismatch", "payment differs from pass in: " + ", ".join(mismatched))

    receipt = Receipt(
        receipt_id=new_id("rcp"),
        pass_id=p.pass_id,
        decision_id=p.decision_id,
        invoice_id=p.invoice_id,
        payee_account=p.payee_account,
        amount_paise=p.amount_paise,
        currency=p.currency,
        paid_at=to_iso(now),
    )
    # Burn + pay in one transaction. The PRIMARY KEY on used_nonces makes the burn atomic:
    # of N concurrent attempts with the same pass, exactly one INSERT succeeds.
    try:
        with db.transaction(conn):
            conn.execute(
                "INSERT INTO used_nonces (nonce, pass_id, used_at) VALUES (?, ?, ?)", (p.nonce, p.pass_id, to_iso(now))
            )
            db.insert_receipt(conn, receipt)
    except sqlite3.IntegrityError:
        raise PayError(409, "replay", "pass already used") from None
    return receipt
