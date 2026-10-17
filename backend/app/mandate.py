"""Mandates: the HMAC-signed record of what the human actually authorised.

Pure functions; the caller supplies the key and the current time.
"""

from datetime import datetime, timedelta
from typing import Any

from app.clock import parse_iso, to_iso
from app.crypto import new_id, sign, verify
from app.models import Mandate, MandateConstraints
from app.verdict import Verdict


def mandate_payload(m: Mandate) -> dict[str, Any]:
    """Everything except the signature: this is what gets signed."""
    return m.model_dump(mode="json", exclude={"signature"})


def create_mandate(
    principal: str, constraints: MandateConstraints, *, key: str, now: datetime, ttl_seconds: int
) -> Mandate:
    if ttl_seconds <= 0:
        raise ValueError("mandate ttl must be positive")
    unsigned = Mandate(
        mandate_id=new_id("mdt"),
        principal=principal,
        action="pay_invoice",
        constraints=constraints,
        created_at=to_iso(now),
        expires_at=to_iso(now + timedelta(seconds=ttl_seconds)),
        signature="",
    )
    return unsigned.model_copy(update={"signature": sign(key, mandate_payload(unsigned))})


def verify_mandate(m: Mandate, *, key: str, now: datetime) -> Verdict:
    """Signature first (so nothing unsigned is trusted), then expiry. Fails closed."""
    if not verify(key, mandate_payload(m), m.signature):
        return Verdict(False, "mandate signature invalid")
    try:
        expires = parse_iso(m.expires_at)
    except ValueError:
        return Verdict(False, "mandate expiry unparseable")
    if now >= expires:
        return Verdict(False, f"mandate expired at {m.expires_at}")
    return Verdict(True, f"signature ok, expires {m.expires_at}")
