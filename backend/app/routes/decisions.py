"""GET /decisions, GET /decisions/{id}. STUB: serves the three example decisions."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app import stub_data
from app.errors import api_error
from app.models import Decision

router = APIRouter(tags=["decisions"])


@router.get("/decisions", response_model=list[Decision])
def list_decisions() -> list[Decision]:
    return list(stub_data.DECISIONS.values())


@router.get("/decisions/{decision_id}", response_model=Decision)
def get_decision(decision_id: str) -> Decision | JSONResponse:
    decision = stub_data.DECISIONS.get(decision_id)
    if decision is None:
        return api_error(404, "not_found", f"no decision {decision_id}")
    return decision
