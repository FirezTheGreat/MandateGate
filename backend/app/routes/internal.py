"""POST /internal/payment-event: payment service → gate, so `payment` events reach the SSE feed.

STUB: accepts and drops the receipt. Phase 4 must authenticate the caller (e.g. an HMAC
header keyed with PASS_KEY) so an agent cannot inject fake payment events into the feed.
Display only: this endpoint never influences a decision.
"""

from fastapi import APIRouter

from app.models import OkResponse, Receipt

router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/payment-event", response_model=OkResponse)
def payment_event(_: Receipt) -> OkResponse:
    return OkResponse(ok=True, detail="stub: event not published yet")
