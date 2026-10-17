"""Gate FastAPI app (port 8000): routers, CORS, startup (settings, schema, fixtures, mode)."""

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app import db, events
from app.clock import to_iso, utc_now
from app.config import load_settings
from app.errors import install_error_handlers
from app.fixtures import load_fixtures
from app.routes import admin, approvals, attacks, decisions, internal, mandates, proposals, sessions, tools, trace
from app.routes import events as events_routes

DASHBOARD_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
AGENT_FACING = re.compile(r"^/(proposals|delegate|tools/[a-z_]+)$")
SESSION_ID = re.compile(r"^[A-Za-z0-9_]{1,80}$")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = load_settings()  # raises ConfigError on missing/placeholder keys: refuse to start
    db.init_gate_db(settings.gate_db_path)
    app.state.settings = settings
    app.state.fixtures = load_fixtures()  # raises FixtureError on bad demo data: refuse to start
    app.state.mode = settings.gate_mode
    yield


def log_suspicious_input(request: Request, exc: RequestValidationError) -> None:
    """CLAUDE.md §2.2: fields an agent was not allowed to send (e.g. `trusted`, `source`) are
    rejected and logged as `suspicious_input`. Only field names are stored, never values."""
    if not AGENT_FACING.match(request.url.path):
        return
    fields = [str(e["loc"][-1])[:64] for e in exc.errors() if e.get("type") == "extra_forbidden"]
    if not fields:
        return
    body = exc.body if isinstance(exc.body, dict) else {}
    sid = body.get("session_id")
    session_id = sid if isinstance(sid, str) and SESSION_ID.match(sid) else None
    conn = db.connect(request.app.state.settings.gate_db_path)
    try:
        with db.transaction(conn):
            events.emit(conn, "suspicious_input", session_id, {"path": request.url.path, "fields": fields[:20]}, to_iso(utc_now()))
    finally:
        conn.close()


app = FastAPI(title="MandateGate", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=DASHBOARD_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
install_error_handlers(app, on_invalid_input=log_suspicious_input)

for module in (mandates, sessions, tools, proposals, approvals, decisions, trace, events_routes, admin, attacks, internal):
    app.include_router(module.router)
