"""Gate FastAPI app (port 8000): routers, CORS, startup schema creation."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import load_settings
from app.db import init_gate_db
from app.errors import install_error_handlers
from app.routes import admin, approvals, attacks, decisions, events, internal, mandates, proposals, tools, trace

DASHBOARD_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = load_settings()  # raises ConfigError on missing/placeholder keys: refuse to start
    init_gate_db(settings.gate_db_path)
    app.state.settings = settings
    yield


app = FastAPI(title="MandateGate", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=DASHBOARD_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
install_error_handlers(app)

for module in (mandates, tools, proposals, approvals, decisions, trace, events, admin, attacks, internal):
    app.include_router(module.router)
