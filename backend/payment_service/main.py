"""Payment service FastAPI app (port 8001): POST /pay, GET /ledger, POST /reset.

A separate trust boundary from the gate. It never pays without a valid one-time pass,
and it has no bypass or debug flag (CLAUDE.md §2 invariant 4).
"""

import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import db
from app.clock import utc_now
from app.config import Settings, load_settings
from app.errors import api_error, install_error_handlers
from app.models import OkResponse, PayRequest, Receipt
from payment_service.verify import PayError, verify_and_pay

DASHBOARD_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = load_settings()  # raises ConfigError on missing/placeholder keys: refuse to start
    db.init_payment_db(settings.pay_db_path)
    app.state.settings = settings
    yield


app = FastAPI(title="MandateGate payment service", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=DASHBOARD_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
install_error_handlers(app)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_conn(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[sqlite3.Connection]:
    conn = db.connect(settings.pay_db_path)
    try:
        yield conn
    finally:
        conn.close()


SettingsDep = Annotated[Settings, Depends(get_settings)]
ConnDep = Annotated[sqlite3.Connection, Depends(get_conn)]


@app.post("/pay", response_model=Receipt)
def pay(req: PayRequest, settings: SettingsDep, conn: ConnDep) -> Receipt | JSONResponse:
    try:
        return verify_and_pay(conn, req, key=settings.pass_key, now=utc_now())
    except PayError as e:
        return api_error(e.status, e.error, e.detail)


@app.get("/ledger", response_model=list[Receipt])
def ledger(conn: ConnDep) -> list[Receipt]:
    return db.list_ledger(conn)


@app.post("/reset", response_model=OkResponse)
def reset(conn: ConnDep) -> OkResponse:
    db.clear_ledger(conn)
    return OkResponse(ok=True, detail="ledger cleared (used nonces are kept, so old passes stay dead)")
