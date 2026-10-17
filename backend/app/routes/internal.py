"""POST /internal/payment-event: payment service → gate, so payments (and refusals) reach the feed.

Authenticated: header X-MandateGate-Signature = hex HMAC(PASS_KEY, canonical(body)), and `sent_at`
must be within FRESH_S of now (limits replays of a captured report). Display only: nothing here
can influence a decision or a pass.
"""

from datetime import timedelta

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from app import db, events
from app.clock import parse_iso, to_iso, utc_now
from app.crypto import verify
from app.deps import ConnDep, SettingsDep
from app.errors import api_error
from app.models import OkResponse, PaymentEventReport

router = APIRouter(prefix="/internal", tags=["internal"])
FRESH_S = 60


@router.post("/payment-event", response_model=OkResponse)
def payment_event(
    report: PaymentEventReport, settings: SettingsDep, conn: ConnDep,
    x_mandategate_signature: str = Header(default=""),
) -> OkResponse | JSONResponse:
    if not verify(settings.pass_key, report.model_dump(mode="json"), x_mandategate_signature):
        return api_error(401, "bad_signature", "payment event is not signed by the payment service")
    now = utc_now()
    try:
        fresh = abs(now - parse_iso(report.sent_at)) <= timedelta(seconds=FRESH_S)
    except ValueError:
        fresh = False
    if not fresh:
        return api_error(401, "stale", f"payment event older than {FRESH_S}s")
    decision = db.get_decision(conn, report.decision_id) if report.decision_id else None
    with db.transaction(conn):
        events.emit(conn, "payment", decision.session_id if decision else None, report.model_dump(mode="json"), to_iso(now))
    return OkResponse(ok=True)
