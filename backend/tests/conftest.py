"""Shared fixtures: isolated temp databases, test keys, and TestClients for both apps."""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app as gate_app
from payment_service.main import app as pay_app

TEST_KEY = "ab" * 32  # every service key in tests (MANDATE_KEY, ROOT_KEY, PASS_KEY)


@dataclass(frozen=True)
class Env:
    gate_db: Path
    pay_db: Path


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    e = Env(gate_db=tmp_path / "gate.db", pay_db=tmp_path / "payment.db")
    monkeypatch.setenv("GATE_DB_PATH", str(e.gate_db))
    monkeypatch.setenv("PAY_DB_PATH", str(e.pay_db))
    monkeypatch.setenv("PASS_TTL_SECONDS", "120")
    for name in ("MANDATE_KEY", "ROOT_KEY", "PASS_KEY"):
        monkeypatch.setenv(name, TEST_KEY)
    return e


@pytest.fixture
def gate(env: Env) -> Iterator[TestClient]:
    with TestClient(gate_app) as client:
        yield client


@pytest.fixture
def pay(env: Env) -> Iterator[TestClient]:
    with TestClient(pay_app) as client:
        pay_app.state.notify = lambda _report: None  # no gate to notify in tests; test_payment_events wires one
        yield client
