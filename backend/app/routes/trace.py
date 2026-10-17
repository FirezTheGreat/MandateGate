"""GET /trace/{decision_id}. STUB: hero-attack graph; the real tracer lands in Phase 4."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app import stub_data
from app.errors import api_error
from app.models import TraceGraph

router = APIRouter(tags=["trace"])


@router.get("/trace/{decision_id}", response_model=TraceGraph)
def get_trace(decision_id: str) -> TraceGraph | JSONResponse:
    trace = stub_data.TRACES.get(decision_id)
    if trace is None:
        return api_error(404, "not_found", f"no trace for {decision_id}")
    return trace
