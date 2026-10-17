"""GET /trace/{decision_id}: the attack-trace graph for React Flow (see tracer.py)."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app import db, tracer
from app.deps import ConnDep
from app.errors import api_error
from app.models import TraceGraph

router = APIRouter(tags=["trace"])


@router.get("/trace/{decision_id}", response_model=TraceGraph)
def get_trace(decision_id: str, conn: ConnDep) -> TraceGraph | JSONResponse:
    decision = db.get_decision(conn, decision_id)
    if decision is None:
        return api_error(404, "not_found", f"no decision {decision_id}")
    calls = tracer.tool_call_records(db.session_tool_calls(conn, decision.session_id, until_ts=decision.created_at))
    return tracer.build_trace(decision, calls, db.session_values(conn, decision.session_id))
