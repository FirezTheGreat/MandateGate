"""One-time passes: HMAC-sealed, single-use, short-lived, bound to exact payment fields.

Only ever issued for an ALLOW decision. Pure: the caller supplies key and time.
"""

from datetime import datetime, timedelta
from typing import Any

from app.clock import to_iso
from app.crypto import new_id, new_nonce, sign
from app.models import Decision, OnePass

MAX_TTL_SECONDS = 600


def pass_payload(p: OnePass) -> dict[str, Any]:
    """Everything except the signature: this is what gets signed and verified."""
    return p.model_dump(mode="json", exclude={"sig"})


def issue_pass(decision: Decision, *, key: str, now: datetime, ttl_seconds: int) -> OnePass:
    if decision.outcome != "ALLOW":
        raise ValueError(f"refusing to issue a pass for a {decision.outcome} decision")
    if decision.mandate_id is None:
        raise ValueError("refusing to issue a pass without a mandate")
    if not 0 < ttl_seconds <= MAX_TTL_SECONDS:
        raise ValueError(f"pass ttl must be in (0, {MAX_TTL_SECONDS}] seconds")
    p = decision.proposal
    unsigned = OnePass(
        pass_id=new_id("pas"),
        decision_id=decision.decision_id,
        mandate_id=decision.mandate_id,
        invoice_id=p.invoice_id,
        payee_account=p.payee_account,
        amount_paise=p.amount_paise,
        currency=p.currency,
        nonce=new_nonce(),
        exp=to_iso(now + timedelta(seconds=ttl_seconds)),
        sig="",
    )
    return unsigned.model_copy(update={"sig": sign(key, pass_payload(unsigned))})
