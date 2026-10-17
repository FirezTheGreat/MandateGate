"""POST /sessions: start one agent run, bound to one mandate (and optionally a demo scenario).
GET /sessions/{id}: look one up (the dashboard follows a run by its session)."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app import db
from app.clock import to_iso, utc_now
from app.crypto import new_id
from app.deps import ConnDep, FixturesDep, ModeDep, SettingsDep
from app.errors import api_error
from app.mandate import verify_mandate
from app.models import Session, SessionCreateRequest

router = APIRouter(tags=["sessions"])


@router.post("/sessions", response_model=Session)
def create_session(req: SessionCreateRequest, settings: SettingsDep, fixtures: FixturesDep, mode: ModeDep, conn: ConnDep) -> Session | JSONResponse:
    now = utc_now()
    mandate = db.get_mandate(conn, req.mandate_id)
    if mandate is None:
        return api_error(404, "unknown_mandate", f"no mandate {req.mandate_id}")
    verdict = verify_mandate(mandate, key=settings.mandate_key, now=now)
    if not verdict.ok:
        return api_error(409, "mandate_invalid", verdict.detail)
    if req.scenario is not None and req.scenario not in fixtures.scenarios:
        return api_error(404, "unknown_scenario", f"no scenario {req.scenario}")
    session = Session(session_id=new_id("ses"), mandate_id=mandate.mandate_id, scenario=req.scenario, mode=mode, created_at=to_iso(now))
    db.insert_session(conn, **session.model_dump())
    return session


@router.get("/sessions/{session_id}", response_model=Session)
def get_session(session_id: str, conn: ConnDep) -> Session | JSONResponse:
    session = db.get_session(conn, session_id)
    if session is None:
        return api_error(404, "not_found", f"no session {session_id}")
    return session
