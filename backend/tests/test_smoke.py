"""Phase 0 smoke tests: both apps boot, stub routes honour the contracts in models.py."""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import ConfigError, load_settings
from app.db import GATE_TABLES, PAYMENT_TABLES, table_names
from app.main import app as gate_app
from app.models import CHECK_ORDER, AttackResults, Decision, TraceGraph
from payment_service.main import app as pay_app

APP_DIR = Path(__file__).resolve().parent.parent / "app"
TEST_KEY = "ab" * 32

FINANCE_TOKEN = {
    "token_id": "tok_finance_example",
    "mandate_id": "mdt_example",
    "caveats": ["agent = finance"],
    "parent_token_id": "tok_root_example",
    "sig": "0" * 64,
}

PROPOSAL = {
    "session_id": "ses_smoke",
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
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    gate_db, pay_db = tmp_path / "gate.db", tmp_path / "payment.db"
    monkeypatch.setenv("GATE_DB_PATH", str(gate_db))
    monkeypatch.setenv("PAY_DB_PATH", str(pay_db))
    for name in ("MANDATE_KEY", "ROOT_KEY", "PASS_KEY"):
        monkeypatch.setenv(name, TEST_KEY)
    return gate_db, pay_db


@pytest.fixture
def gate(env: tuple[Path, Path]) -> Iterator[TestClient]:
    with TestClient(gate_app) as client:
        yield client


@pytest.fixture
def pay(env: tuple[Path, Path]) -> Iterator[TestClient]:
    with TestClient(pay_app) as client:
        yield client


# --------------------------------------------------------------------------- startup & config


def test_schemas_created_on_startup(gate: TestClient, pay: TestClient, env: tuple[Path, Path]) -> None:
    gate_db, pay_db = env
    assert set(GATE_TABLES) <= table_names(gate_db)
    assert set(PAYMENT_TABLES) <= table_names(pay_db)


@pytest.mark.parametrize("bad", ["", "change-me-32-bytes-hex", "tooshort"])
def test_placeholder_or_weak_keys_refuse_to_start(env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv("PASS_KEY", bad)
    with pytest.raises(ConfigError):
        load_settings()
    with pytest.raises(ConfigError), TestClient(pay_app):
        pass


# --------------------------------------------------------------------------- decisions


def test_dec_example_matches_contract(gate: TestClient) -> None:
    r = gate.get("/decisions/dec_example")
    assert r.status_code == 200
    body = r.json()
    Decision.model_validate(body)
    assert body["outcome"] == "BLOCK" and body["mode"] == "gated"
    assert body["one_pass"] is None and body["trace_available"] is True
    assert body["proposal"]["payee_account"] == "EVE-777"
    assert [c["check"] for c in body["checks"]] == list(CHECK_ORDER)
    payee = body["checks"][CHECK_ORDER.index("payee_provenance")]
    assert payee["status"] == "fail"
    assert payee["required"] == "vendor_registry:acme"
    assert payee["found"] == ["email:1842 (untrusted)"]


def test_every_stub_decision_reports_all_checks_in_order(gate: TestClient) -> None:
    decisions = gate.get("/decisions").json()
    assert {d["outcome"] for d in decisions} == {"ALLOW", "BLOCK", "STEP_UP"}
    for d in decisions:
        assert [c["check"] for c in d["checks"]] == list(CHECK_ORDER), d["decision_id"]
        assert "token" not in d["proposal"]  # bearer credential never echoed back


def test_baseline_decision_marks_provenance_skipped(gate: TestClient) -> None:
    d = gate.get("/decisions/dec_baseline_example").json()
    status = {c["check"]: c["status"] for c in d["checks"]}
    assert d["mode"] == "baseline"
    assert status["payee_provenance"] == status["amount_provenance"] == "skipped"


def test_step_up_example_is_step_up_not_block(gate: TestClient) -> None:
    d = gate.get("/decisions/dec_stepup_example").json()
    status = {c["check"]: c["status"] for c in d["checks"]}
    assert d["outcome"] == "STEP_UP"
    assert status["delegation_chain"] == "pass" and status["amount_within_limit"] == "fail"


def test_unknown_decision_is_structured_404(gate: TestClient) -> None:
    r = gate.get("/decisions/dec_nope")
    assert r.status_code == 404
    assert set(r.json()) == {"error", "detail"}


# --------------------------------------------------------------------------- tools & proposals


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
    body = r.json()
    assert body["outcome"] == "BLOCK" and body["one_pass"] is None
    assert body["session_id"] == "ses_smoke"


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


# --------------------------------------------------------------------------- admin, attacks, internal


def test_mode_round_trip(gate: TestClient) -> None:
    assert gate.post("/admin/mode", json={"mode": "baseline"}).json() == {"mode": "baseline"}
    assert gate.get("/admin/mode").json() == {"mode": "baseline"}
    gate.post("/admin/mode", json={"mode": "gated"})


def test_run_scenario_rejects_unsafe_name(gate: TestClient) -> None:
    assert gate.post("/admin/run-scenario", json={"scenario": "hero_attack"}).status_code == 200
    assert gate.post("/admin/run-scenario", json={"scenario": "x && del *"}).status_code == 422


def test_attack_results_shape(gate: TestClient) -> None:
    AttackResults.model_validate(gate.get("/attacks/results").json())


def test_internal_payment_event_accepts_receipt(gate: TestClient, pay: TestClient) -> None:
    receipt = pay.get("/ledger").json()[0]
    assert gate.post("/internal/payment-event", json=receipt).status_code == 200


# --------------------------------------------------------------------------- payment service


def test_pay_without_pass_is_401(pay: TestClient) -> None:
    r = pay.post("/pay", json={"payment": PAYMENT})
    assert r.status_code == 401
    assert r.json()["error"] == "missing_pass"


def test_pay_legacy_pass_key_rejected(pay: TestClient) -> None:
    r = pay.post("/pay", json={"pass": None, "payment": PAYMENT})
    assert r.status_code == 422


def test_ledger_ok(pay: TestClient) -> None:
    r = pay.get("/ledger")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# --------------------------------------------------------------------------- invariants


def test_cors_allows_dashboard(gate: TestClient) -> None:
    r = gate.get("/decisions/dec_example", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_gate_never_imports_an_llm() -> None:
    """Invariant 1: no LLM in the decision path."""
    pattern = re.compile(r"^\s*(import|from)\s+(anthropic|openai)\b", re.MULTILINE)
    offenders = [p.name for p in APP_DIR.rglob("*.py") if pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == []
