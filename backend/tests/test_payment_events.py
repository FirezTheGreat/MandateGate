"""Payment service → gate: signed `payment` events (paid and refused) reach the feed; forgeries don't."""

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agents import run_scenario
from agents.gate_client import GateClient
from app.clock import to_iso, utc_now
from app.crypto import sign
from app.models import PaymentEventReport
from payment_service.main import app as pay_app
from payment_service.notify import SIGNATURE_HEADER, make_notifier
from tests.conftest import TEST_KEY
from tests.gatekit import GateKit, pay_body


@pytest.fixture
def wired(gate: TestClient, pay: TestClient) -> GateClient:
    """Deliver the payment service's notifications to the gate synchronously."""
    pay_app.state.notify = make_notifier(gate, TEST_KEY, background=False)
    return GateClient(gate, pay)


def payment_events(kit: GateKit, sid: str) -> list[dict[str, Any]]:
    return [e["data"] for e in kit.events(sid) if e["type"] == "payment"]


def test_paid_payment_appears_in_the_session_feed(wired: GateClient, gate: TestClient) -> None:
    r = run_scenario.run("happy", "gated", "scripted", client=wired, log=lambda _: None)
    events = payment_events(GateKit(gate), r["session_id"])
    assert [(e["status"], e["receipt"]["payee_account"], e["receipt"]["amount_paise"]) for e in events] == [("paid", "ACME-4410-2291", 485000)]


def test_baseline_attacker_payment_appears_in_the_feed(wired: GateClient, gate: TestClient) -> None:
    r = run_scenario.run("hero_attack", "baseline", "scripted", client=wired, log=lambda _: None)
    assert payment_events(GateKit(gate), r["session_id"])[0]["receipt"]["payee_account"] == "EVE-777"


def test_refused_replay_appears_in_the_feed(wired: GateClient, gate: TestClient, pay: TestClient) -> None:
    kit = GateKit(gate)
    sid, tok = kit.start("happy")
    kit.investigate(sid, tok, emails=())
    d = kit.propose(sid, tok, "ACME-4410-2291").json()
    assert pay.post("/pay", json=pay_body(d["one_pass"])).status_code == 200
    assert pay.post("/pay", json=pay_body(d["one_pass"])).status_code == 409
    assert [(e["status"], e.get("error")) for e in payment_events(kit, sid)] == [("paid", None), ("refused", "replay")]


def test_payment_without_a_pass_is_reported_without_a_session(wired: GateClient, gate: TestClient, pay: TestClient) -> None:
    payment = {"invoice_id": "INV-1048", "payee_account": "EVE-777", "amount_paise": 485000, "currency": "INR"}
    assert pay.post("/pay", json={"payment": payment}).status_code == 401


def report(**kw: Any) -> dict[str, Any]:
    base = {"status": "paid", "sent_at": to_iso(utc_now()), "payee_account": "EVE-777", "amount_paise": 485000}
    return PaymentEventReport.model_validate({**base, **kw}).model_dump(mode="json")


@pytest.mark.parametrize(
    "headers",
    [{}, {SIGNATURE_HEADER: "0" * 64}, {SIGNATURE_HEADER: "not-hex"}],
    ids=["unsigned", "wrong_signature", "garbage"],
)
def test_forged_payment_events_are_rejected(gate: TestClient, headers: dict[str, str]) -> None:
    r = gate.post("/internal/payment-event", json=report(), headers=headers)
    assert (r.status_code, r.json()["error"]) == (401, "bad_signature")


def test_stale_payment_events_are_rejected(gate: TestClient) -> None:
    body = report(sent_at=to_iso(utc_now() - timedelta(minutes=5)))
    r = gate.post("/internal/payment-event", json=body, headers={SIGNATURE_HEADER: sign(TEST_KEY, body)})
    assert (r.status_code, r.json()["error"]) == (401, "stale")


def test_signed_payment_event_is_accepted(gate: TestClient) -> None:
    body = report()
    r = gate.post("/internal/payment-event", json=body, headers={SIGNATURE_HEADER: sign(TEST_KEY, body)})
    assert r.status_code == 200


def test_a_broken_notifier_never_breaks_a_payment(gate: TestClient, pay: TestClient) -> None:
    def boom(_: PaymentEventReport) -> None:
        raise RuntimeError("gate down")

    pay_app.state.notify = boom
    kit = GateKit(gate)
    sid, tok = kit.start("happy")
    kit.investigate(sid, tok, emails=())
    d = kit.propose(sid, tok, "ACME-4410-2291").json()
    assert pay.post("/pay", json=pay_body(d["one_pass"])).status_code == 200
