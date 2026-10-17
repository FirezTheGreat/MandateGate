"""GET /approvals, POST /approvals/{decision_id}. STUB: real queue lands in Phase 4."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app import stub_data
from app.errors import api_error
from app.models import ApprovalRequest, CheckResult, Decision, PendingApproval

router = APIRouter(tags=["approvals"])


@router.get("/approvals", response_model=list[PendingApproval])
def list_approvals() -> list[PendingApproval]:
    return stub_data.PENDING_APPROVALS


@router.post("/approvals/{decision_id}", response_model=Decision)
def resolve_approval(decision_id: str, req: ApprovalRequest) -> Decision | JSONResponse:
    if decision_id not in {a.decision_id for a in stub_data.PENDING_APPROVALS}:
        return api_error(404, "not_found", f"no pending approval for {decision_id}")
    base = stub_data.DEC_STEPUP_EXAMPLE
    verdict = "approved" if req.approve else "denied"
    limit_check = CheckResult(
        check="amount_within_limit",
        passed=req.approve,
        detail=f"520000 > 500000, {verdict} by human",
    )
    checks = [limit_check if c.check == "amount_within_limit" else c for c in base.checks]
    if not req.approve:
        return base.model_copy(update={"outcome": "BLOCK", "checks": checks})
    fake_pass = stub_data.EXAMPLE_PASS.model_copy(
        update={
            "pass_id": "pas_stepup_example",
            "decision_id": decision_id,
            "invoice_id": "INV-1052",
            "amount_paise": 520000,
        }
    )
    return base.model_copy(update={"outcome": "ALLOW", "checks": checks, "pass_": fake_pass})
