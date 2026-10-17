"""GET /decisions (newest first), GET /decisions/{id}."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app import db
from app.deps import ConnDep
from app.errors import api_error
from app.models import Decision

router = APIRouter(tags=["decisions"])


@router.get("/decisions", response_model=list[Decision])
def list_decisions(conn: ConnDep) -> list[Decision]:
    return db.list_decisions(conn)


@router.get("/decisions/{decision_id}", response_model=Decision)
def get_decision(decision_id: str, conn: ConnDep) -> Decision | JSONResponse:
    decision = db.get_decision(conn, decision_id)
    if decision is None:
        return api_error(404, "not_found", f"no decision {decision_id}")
    return decision
