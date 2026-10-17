"""Smoke tests: both apps boot, config fails closed, remaining stubs honour the contracts,
and cross-cutting invariants hold. Feature behaviour lives in the per-module test files."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import ConfigError, load_settings
from app.db import GATE_TABLES, PAYMENT_TABLES, table_names
from app.fixtures import load_fixtures
from app.models import AttackResults
from payment_service.main import app as pay_app
from tests.conftest import Env

APP_DIR = Path(__file__).resolve().parent.parent / "app"


# --------------------------------------------------------------------------- startup & config


def test_schemas_created_on_startup(gate: TestClient, pay: TestClient, env: Env) -> None:
    assert set(GATE_TABLES) <= table_names(env.gate_db)
    assert set(PAYMENT_TABLES) <= table_names(env.pay_db)


@pytest.mark.parametrize("bad", ["", "change-me-32-bytes-hex", "tooshort"])
def test_placeholder_or_weak_keys_refuse_to_start(env: Env, monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv("PASS_KEY", bad)
    with pytest.raises(ConfigError):
        load_settings()
    with pytest.raises(ConfigError), TestClient(pay_app):
        pass


@pytest.mark.parametrize("bad", ["0", "-5", "601", "two minutes"])
def test_bad_pass_ttl_refuses_to_start(env: Env, monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv("PASS_TTL_SECONDS", bad)
    with pytest.raises(ConfigError):
        load_settings()


def test_old_gate_schema_is_rebuilt(tmp_path: Path) -> None:
    """A dev DB from an earlier phase (no user_version, old tables) is rebuilt, not half-used."""
    import sqlite3

    from app.db import init_gate_db

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as old:
        old.execute('CREATE TABLE "values" (value_id TEXT)')
        old.execute("CREATE TABLE approvals (decision_id TEXT PRIMARY KEY, status TEXT)")
    old.close()
    init_gate_db(path)
    with sqlite3.connect(path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(approvals)")}
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    conn.close()
    assert "limit_paise" in cols and "values" not in tables


def test_unknown_gate_mode_falls_back_to_gated(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GATE_MODE", "off")
    assert load_settings().gate_mode == "gated"


def test_fixtures_are_valid() -> None:
    fx = load_fixtures()
    assert {"happy", "hero_attack", "step_up"} <= set(fx.scenarios)
    assert fx.vendors["acme"]["bank"]["account_number"] == "ACME-4410-2291"
    assert fx.emails["1842"]["from"] == "accounts@acme-supp1ies.com"


# --------------------------------------------------------------------------- errors & stubs


def test_unknown_decision_is_structured_404(gate: TestClient) -> None:
    r = gate.get("/decisions/dec_nope")
    assert r.status_code == 404
    assert set(r.json()) == {"error", "detail"}


def test_run_scenario_rejects_unsafe_name(gate: TestClient) -> None:
    assert gate.post("/admin/run-scenario", json={"scenario": "x && del *"}).status_code == 422


def test_attack_results_shape(gate: TestClient) -> None:
    AttackResults.model_validate(gate.get("/attacks/results").json())


def test_ledger_starts_empty(pay: TestClient) -> None:
    assert pay.get("/ledger").json() == []


# --------------------------------------------------------------------------- invariants


def test_cors_allows_dashboard(gate: TestClient) -> None:
    r = gate.get("/tools", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_refuses_other_origins(gate: TestClient) -> None:
    r = gate.get("/tools", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_gate_never_imports_an_llm() -> None:
    """Invariant 1: no LLM in the decision path."""
    pattern = re.compile(r"^\s*(import|from)\s+(anthropic|openai)\b", re.MULTILINE)
    offenders = [p.name for p in APP_DIR.rglob("*.py") if pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_no_float_money_in_contracts() -> None:
    """Invariant 8: every *_paise field in models.py is the strict integer Paise type."""
    source = (APP_DIR / "models.py").read_text(encoding="utf-8")
    fields = re.findall(r"^\s+(\w*paise\w*):\s*([^\n=]+)", source, re.MULTILINE)
    assert fields and all(t.strip() in ("Paise", "Paise | None") for _, t in fields), fields
