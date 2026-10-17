"""GET /approvals (pending STEP_UPs), POST /approvals/{decision_id} {approve} → Decision (+ pass)."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app import approvals
from app.clock import utc_now
from app.deps import ConnDep, SettingsDep
from app.errors import api_error
from app.models import ApprovalRequest, Decision, PendingApproval

router = APIRouter(tags=["approvals"])


@router.get("/approvals", response_model=list[PendingApproval])
def list_approvals(conn: ConnDep) -> list[PendingApproval]:
    return approvals.list_pending(conn, utc_now())


@router.post("/approvals/{decision_id}", response_model=Decision)
def resolve_approval(decision_id: str, req: ApprovalRequest, settings: SettingsDep, conn: ConnDep) -> Decision | JSONResponse:
    try:
        return approvals.resolve(conn, decision_id=decision_id, approve=req.approve, settings=settings, now=utc_now())
    except approvals.ApprovalError as e:
        return api_error(e.status, e.error, e.detail)
