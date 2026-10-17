"""POST /admin/mode, POST /admin/reset. STUB: mode is held in memory; reset is a no-op."""

from fastapi import APIRouter

from app.models import GateMode, ModeRequest, ModeState, OkResponse

router = APIRouter(prefix="/admin", tags=["admin"])

_state: dict[str, GateMode] = {"mode": "gated"}


@router.post("/mode", response_model=ModeState)
def set_mode(req: ModeRequest) -> ModeState:
    _state["mode"] = req.mode
    return ModeState(mode=req.mode)


@router.post("/reset", response_model=OkResponse)
def reset() -> OkResponse:
    return OkResponse(ok=True, detail="stub: nothing to reset yet")
