"""/admin/mode (GET, POST), /admin/reset, /admin/run-scenario.

Demo controls. Unauthenticated by design for the hackathon: never expose them to agent tooling.
"""

import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import db
from app.deps import ConnDep, FixturesDep, ModeDep
from app.errors import api_error
from app.fixtures import FixtureError, load_fixtures
from app.models import ModeRequest, ModeState, OkResponse, RunScenarioRequest, RunScenarioStarted
from app.runner import RunnerError

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


def agent_label(agent: str) -> str:
    """What the dashboard shows about who is acting (CLAUDE.md §8 demo rule: label the simulated agent)."""
    if agent == "scripted":
        return "Simulated fooled agent (scripted)"
    provider = os.environ.get("LLM_PROVIDER", "anthropic").strip() or "anthropic"
    model = os.environ.get("LLM_MODEL", "").strip() or ("claude-opus-5-5" if provider == "anthropic" else "LLM")
    return f"AI agent ({model})"


@router.post("/run-scenario", response_model=RunScenarioStarted)
def run_scenario(req: RunScenarioRequest, request: Request, mode: ModeDep, fixtures: FixturesDep) -> RunScenarioStarted | JSONResponse:
    """Start `agents.run_scenario` in the gate's current mode; returns once its session exists."""
    if req.scenario not in fixtures.scenarios:
        return api_error(404, "unknown_scenario", f"no scenario {req.scenario}")
    try:
        session_id = request.app.state.runner.start(req.scenario, mode, req.agent)
    except RunnerError as e:
        return api_error(e.status, e.error, e.detail)
    return RunScenarioStarted(session_id=session_id, scenario=req.scenario, mode=mode, agent=req.agent, agent_label=agent_label(req.agent))
