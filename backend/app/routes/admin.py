"""/admin/mode (GET, POST), /admin/reset, /admin/run-scenario.

STUB: mode is held in memory; reset is a no-op; run-scenario does not spawn anything yet
(Phase 3/5 wire it to `python -m agents.run_scenario` in a subprocess).
"""

from fastapi import APIRouter

from app.models import GateMode, ModeRequest, ModeState, OkResponse, RunScenarioRequest, RunScenarioStarted

router = APIRouter(prefix="/admin", tags=["admin"])

_state: dict[str, GateMode] = {"mode": "gated"}


@router.get("/mode", response_model=ModeState)
def get_mode() -> ModeState:
    return ModeState(mode=_state["mode"])


@router.post("/mode", response_model=ModeState)
def set_mode(req: ModeRequest) -> ModeState:
    _state["mode"] = req.mode
    return ModeState(mode=req.mode)


@router.post("/reset", response_model=OkResponse)
def reset() -> OkResponse:
    return OkResponse(ok=True, detail="stub: nothing to reset yet")


@router.post("/run-scenario", response_model=RunScenarioStarted)
def run_scenario(req: RunScenarioRequest) -> RunScenarioStarted:
    return RunScenarioStarted(session_id="ses_example", scenario=req.scenario, mode=_state["mode"], agent=req.agent)
