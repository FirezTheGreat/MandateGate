"""Payment service FastAPI app (port 8001): POST /pay, GET /ledger, POST /reset.

A separate trust boundary from the gate. It never pays without a valid one-time pass,
and it has no bypass or debug flag (CLAUDE.md §2 invariant 4).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import load_settings
from app.db import init_payment_db
from app.errors import api_error, install_error_handlers
from app.models import OkResponse, PayRequest, Receipt
from app.stub_data import LEDGER

DASHBOARD_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_payment_db(load_settings().pay_db_path)
    yield


app = FastAPI(title="MandateGate payment service", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=DASHBOARD_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
install_error_handlers(app)


@app.post("/pay", response_model=Receipt)
def pay(req: PayRequest) -> JSONResponse:
    # STUB (Phase 0): refuses everything. Phase 1 replaces this with verify.py:
    # sig → exp → exact field match → atomic nonce burn → ledger → receipt.
    if req.one_pass is None:
        return api_error(401, "missing_pass", "a one-time pass is required")
    return api_error(503, "not_implemented", "pass verification lands in Phase 1; refusing to pay")


@app.get("/ledger", response_model=list[Receipt])
def ledger() -> list[Receipt]:
    return LEDGER  # STUB: example rows until Phase 1 reads the real ledger table


@app.post("/reset", response_model=OkResponse)
def reset() -> OkResponse:
    return OkResponse(ok=True, detail="stub: nothing to reset yet")
