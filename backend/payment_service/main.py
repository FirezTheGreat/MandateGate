"""Payment service FastAPI app (port 8001): POST /pay, GET /ledger, POST /reset.

A separate trust boundary from the gate. It never pays without a valid one-time pass,
and it has no bypass or debug flag (CLAUDE.md §2 invariant 4).
"""

import logging
import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import db
from app.clock import to_iso, utc_now
from app.config import Settings, load_settings
from app.errors import api_error, install_error_handlers
from app.guard import RequestGuard
from app.models import OkResponse, PaymentEventReport, PayRequest, Receipt
from payment_service.notify import make_notifier
from payment_service.verify import PayError, verify_and_pay

log = logging.getLogger("mandategate.payment")

DASHBOARD_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = load_settings()  # raises ConfigError on missing/placeholder keys: refuse to start
    db.init_payment_db(settings.pay_db_path)
    app.state.settings = settings
    gate_http = httpx.Client(base_url=settings.gate_url, timeout=2)
    app.state.notify = make_notifier(gate_http, settings.pass_key)
    yield
    gate_http.close()


app = FastAPI(title="MandateGate payment service", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=DASHBOARD_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.add_middleware(RequestGuard, origins=DASHBOARD_ORIGINS)  # outermost: Host + cross-site POST checks first
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
def pay(req: PayRequest, request: Request, settings: SettingsDep, conn: ConnDep) -> Receipt | JSONResponse:
    now = utc_now()
    p = req.one_pass
    try:
        receipt = verify_and_pay(conn, req, key=settings.pass_key, now=now)
        report = PaymentEventReport(status="paid", sent_at=to_iso(now), receipt=receipt, pass_id=receipt.pass_id,
                                    decision_id=receipt.decision_id, payee_account=receipt.payee_account, amount_paise=receipt.amount_paise)
        response: Receipt | JSONResponse = receipt
    except PayError as e:
        report = PaymentEventReport(status="refused", sent_at=to_iso(now), error=e.error, detail=e.detail,
                                    pass_id=p.pass_id if p else None, decision_id=p.decision_id if p else None,
                                    payee_account=req.payment.payee_account, amount_paise=req.payment.amount_paise)
        response = api_error(e.status, e.error, e.detail)
    try:
        request.app.state.notify(report)
    except Exception:  # display only: a notification problem must never change the payment outcome
        log.exception("payment event notification failed")
    return response


@app.get("/ledger", response_model=list[Receipt])
def ledger(conn: ConnDep) -> list[Receipt]:
    return db.list_ledger(conn)


@app.post("/reset", response_model=OkResponse)
def reset(conn: ConnDep) -> OkResponse:
    db.clear_ledger(conn)
    return OkResponse(ok=True, detail="ledger cleared (used nonces are kept, so old passes stay dead)")
