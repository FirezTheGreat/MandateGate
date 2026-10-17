"""/admin/mode (GET, POST), /admin/reset, /admin/run-scenario.

Demo controls. Unauthenticated by design for the hackathon: never expose them to agent tooling.
`/admin/run-scenario` is still a stub (Phase 3/5 spawn `python -m agents.run_scenario`).
"""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import db
from app.deps import ConnDep, ModeDep
from app.errors import api_error
from app.fixtures import FixtureError, load_fixtures
from app.models import ModeRequest, ModeState, OkResponse, RunScenarioRequest, RunScenarioStarted

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("mandategate.admin")


@router.get("/mode", response_model=ModeState)
def get_mode(mode: ModeDep) -> ModeState:
    return ModeState(mode=mode)


@router.post("/mode", response_model=ModeState)
def set_mode(req: ModeRequest, request: Request) -> ModeState:
    request.app.state.mode = req.mode
    return ModeState(mode=req.mode)


@router.post("/reset", response_model=OkResponse)
def reset(request: Request, conn: ConnDep) -> OkResponse | JSONResponse:
    """Wipe all gate state (mandates, sessions, values, decisions, passes, approvals, events)
    and reload fixtures from disk. The mode is kept. The payment service resets separately."""
    try:
        fixtures = load_fixtures()
    except FixtureError as e:
        log.error("reset refused: %s", e)
        return api_error(500, "fixtures_invalid", "fixtures failed validation; run `python -m scripts.seed`")
    db.wipe_gate(conn)
    request.app.state.fixtures = fixtures
    return OkResponse(ok=True, detail="gate state wiped, fixtures reloaded")


@router.post("/run-scenario", response_model=RunScenarioStarted)
def run_scenario(req: RunScenarioRequest, mode: ModeDep) -> RunScenarioStarted:
    return RunScenarioStarted(session_id="ses_example", scenario=req.scenario, mode=mode, agent=req.agent)
