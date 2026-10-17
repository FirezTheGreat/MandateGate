"""POST /mandates (human creates a signed mandate + root token), POST /delegate (attenuate)."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app import db, events
from app.clock import to_iso, utc_now
from app.delegation import CaveatError, attenuate, detect_escalation, mint_root, root_caveats, verify_chain
from app.deps import ConnDep, SettingsDep
from app.errors import api_error
from app.mandate import create_mandate
from app.models import DelegateRequest, DelegationToken, MandateCreated, MandateCreateRequest

router = APIRouter(tags=["mandates"])


@router.post("/mandates", response_model=MandateCreated)
def post_mandate(req: MandateCreateRequest, settings: SettingsDep, conn: ConnDep) -> MandateCreated:
    now = utc_now()
    mandate = create_mandate(req.principal, req.constraints, key=settings.mandate_key, now=now, ttl_seconds=req.ttl_seconds)
    token = mint_root(mandate.mandate_id, root_caveats(req.constraints.max_amount_paise), root_key=settings.root_key)
    with db.transaction(conn):
        db.insert_mandate(conn, mandate)
        db.insert_token(conn, token, to_iso(now))
    return MandateCreated(mandate=mandate, token=token)


@router.post("/delegate", response_model=DelegationToken)
def post_delegate(req: DelegateRequest, settings: SettingsDep, conn: ConnDep) -> DelegationToken | JSONResponse:
    # Attenuation itself needs no key, but the gate only extends tokens it can verify.
    verdict = verify_chain(req.token, root_key=settings.root_key)
    if not verdict.ok:
        return api_error(401, "invalid_token", verdict.detail)
    try:
        child = attenuate(req.token, req.caveats)
    except CaveatError as e:
        return api_error(400, "invalid_caveat", str(e))
    ts = to_iso(utc_now())
    # A widening caveat has no effect (conjunction), but the attempt is worth showing.
    escalations = detect_escalation(child.caveats)
    with db.transaction(conn):
        db.insert_token(conn, child, ts)
        if escalations:
            events.emit(conn, "escalation_attempt", None, {
                "token_id": child.token_id, "mandate_id": child.mandate_id, "caveats": escalations,
            }, ts)
    return child
