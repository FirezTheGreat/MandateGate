"""Phase 0 smoke tests: both apps boot, stub routes honour the contracts in models.py."""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import GATE_TABLES, PAYMENT_TABLES, table_names
from app.main import app as gate_app
from app.models import Decision, TraceGraph
from payment_service.main import app as pay_app

APP_DIR = Path(__file__).resolve().parent.parent / "app"

FINANCE_TOKEN = {
    "token_id": "tok_finance_example",
    "mandate_id": "mdt_example",
    "caveats": ["agent = finance"],
    "parent_token_id": "tok_root_example",
    "sig": "0" * 64,
}

PROPOSAL = {
    "session_id": "ses_example",
    "token": FINANCE_TOKEN,
    "agent_id": "finance",
    "invoice_id": "INV-1048",
    "vendor_id": "acme",
    "payee_account": "EVE-777",
    "amount_paise": 485000,
    "currency": "INR",
    "memo": "Acme bank change per email",
}

PAYMENT = {"invoice_id": "INV-1048", "payee_account": "ACME-4410-2291", "amount_paise": 485000, "currency": "INR"}


@pytest.fixture
def db_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    gate_db, pay_db = tmp_path / "gate.db", tmp_path / "payment.db"
    monkeypatch.setenv("GATE_DB_PATH", str(gate_db))
    monkeypatch.setenv("PAY_DB_PATH", str(pay_db))
    return gate_db, pay_db


@pytest.fixture
def gate(db_paths: tuple[Path, Path]) -> Iterator[TestClient]:
    with TestClient(gate_app) as client:
        yield client


@pytest.fixture
def pay(db_paths: tuple[Path, Path]) -> Iterator[TestClient]:
    with TestClient(pay_app) as client:
        yield client


def test_schemas_created_on_startup(gate: TestClient, pay: TestClient, db_paths: tuple[Path, Path]) -> None:
    gate_db, pay_db = db_paths
    assert set(GATE_TABLES) <= table_names(gate_db)
    assert set(PAYMENT_TABLES) <= table_names(pay_db)


def test_dec_example_matches_contract(gate: TestClient) -> None:
    r = gate.get("/decisions/dec_example")
    assert r.status_code == 200
    body = r.json()
    Decision.model_validate(body)
    assert body["outcome"] == "BLOCK"
    assert body["pass"] is None and body["trace_available"] is True
    checks = {c["check"]: c for c in body["checks"]}
    assert set(checks) == {
        "mandate_valid",
        "delegation_chain",
        "invoice_matches_mandate",
        "amount_within_limit",
        "payee_provenance",
        "amount_provenance",
    }
    assert checks["payee_provenance"]["passed"] is False
    assert checks["payee_provenance"]["required"] == "vendor_registry:acme"
    assert checks["payee_provenance"]["found"] == ["email:1842 (untrusted)"]


def test_unknown_decision_is_structured_404(gate: TestClient) -> None:
    r = gate.get("/decisions/dec_nope")
    assert r.status_code == 404
    assert set(r.json()) == {"error", "detail"}


def test_tools_listed(gate: TestClient) -> None:
    names = {t["name"] for t in gate.get("/tools").json()}
    assert names == {"list_inbox", "read_email", "get_invoice", "get_vendor"}


def test_read_email_1842_serves_fixture(gate: TestClient) -> None:
    r = gate.post(
        "/tools/read_email",
        json={"session_id": "ses_example", "agent_id": "finance", "token": FINANCE_TOKEN, "args": {"email_id": "1842"}},
    )
    assert r.status_code == 200
    email = r.json()["result"]
    assert email["from"] == "accounts@acme-supp1ies.com"
    assert "EVE-777" in email["body"] and "INV-1048" in email["body"]


def test_stub_proposal_fails_closed(gate: TestClient) -> None:
    r = gate.post("/proposals", json=PROPOSAL)
    assert r.status_code == 200
    assert r.json()["outcome"] == "BLOCK"
    assert r.json()["pass"] is None


def test_proposal_with_smuggled_trust_field_rejected(gate: TestClient) -> None:
    r = gate.post("/proposals", json={**PROPOSAL, "trusted": True})
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_request"


def test_proposal_with_float_amount_rejected(gate: TestClient) -> None:
    r = gate.post("/proposals", json={**PROPOSAL, "amount_paise": 4850.0})
    assert r.status_code == 422


def test_trace_is_react_flow_shaped(gate: TestClient) -> None:
    trace = TraceGraph.model_validate(gate.get("/trace/dec_example").json())
    node_ids = {n.id for n in trace.nodes}
    assert all(e.source in node_ids and e.target in node_ids for e in trace.edges)


def test_pay_without_pass_is_401(pay: TestClient) -> None:
    r = pay.post("/pay", json={"payment": PAYMENT})
    assert r.status_code == 401
    assert r.json()["error"] == "missing_pass"


def test_ledger_ok(pay: TestClient) -> None:
    r = pay.get("/ledger")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_cors_allows_dashboard(gate: TestClient) -> None:
    r = gate.get("/decisions/dec_example", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_gate_never_imports_an_llm() -> None:
    """Invariant 1: no LLM in the decision path."""
    pattern = re.compile(r"^\s*(import|from)\s+(anthropic|openai)\b", re.MULTILINE)
    offenders = [p.name for p in APP_DIR.rglob("*.py") if pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == []
