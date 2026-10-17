"""Payment service: never pays without a valid, unexpired, exactly-matching, unused pass."""

import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import db
from app.clock import utc_now
from app.models import OnePass, PayRequest
from app.passes import issue_pass
from payment_service.verify import PayError, verify_and_pay
from tests.conftest import TEST_KEY, Env
from tests.test_passes import decision


def fresh_pass(now: datetime | None = None, key: str = TEST_KEY) -> OnePass:
    return issue_pass(decision(), key=key, now=now or utc_now(), ttl_seconds=120)


def payment_of(p: OnePass, **changes: Any) -> dict[str, Any]:
    base = {"invoice_id": p.invoice_id, "payee_account": p.payee_account, "amount_paise": p.amount_paise, "currency": p.currency}
    return {**base, **changes}


def body(p: OnePass, **payment_changes: Any) -> dict[str, Any]:
    return {"one_pass": p.model_dump(mode="json"), "payment": payment_of(p, **payment_changes)}


def ledger(pay: TestClient) -> list[dict[str, Any]]:
    r = pay.get("/ledger")
    assert r.status_code == 200
    return r.json()


# --------------------------------------------------------------------------- happy path


def test_valid_pass_pays_and_writes_ledger(pay: TestClient) -> None:
    p = fresh_pass()
    r = pay.post("/pay", json=body(p))
    assert r.status_code == 200, r.text
    receipt = r.json()
    assert receipt["receipt_id"].startswith("rcp_")
    assert (receipt["pass_id"], receipt["decision_id"]) == (p.pass_id, p.decision_id)
    assert (receipt["payee_account"], receipt["amount_paise"]) == ("ACME-4410-2291", 485000)
    rows = ledger(pay)
    assert rows == [receipt]
    assert isinstance(rows[0]["amount_paise"], int)


# --------------------------------------------------------------------------- bypass & signature


def test_no_pass_is_401(pay: TestClient) -> None:
    p = fresh_pass()
    r = pay.post("/pay", json={"payment": payment_of(p)})
    assert (r.status_code, r.json()["error"]) == (401, "missing_pass")
    assert ledger(pay) == []


def test_altered_signature_is_401(pay: TestClient) -> None:
    p = fresh_pass()
    flipped = p.sig[:-1] + ("0" if p.sig[-1] != "0" else "1")
    r = pay.post("/pay", json=body(p.model_copy(update={"sig": flipped})))
    assert (r.status_code, r.json()["error"]) == (401, "bad_signature")


def test_pass_signed_with_wrong_key_is_401(pay: TestClient) -> None:
    r = pay.post("/pay", json=body(fresh_pass(key="cd" * 32)))
    assert (r.status_code, r.json()["error"]) == (401, "bad_signature")


@pytest.mark.parametrize(
    "field,value",
    [("amount_paise", 4850000), ("payee_account", "EVE-777"), ("invoice_id", "INV-9999"), ("exp", "2099-01-01T00:00:00Z")],
)
def test_tampering_with_the_pass_itself_is_401(pay: TestClient, field: str, value: Any) -> None:
    """Edit the pass AND the payment to match: the signature no longer covers the fields."""
    p = fresh_pass()
    tampered = p.model_copy(update={field: value})
    r = pay.post("/pay", json={"one_pass": tampered.model_dump(mode="json"), "payment": payment_of(tampered)})
    assert (r.status_code, r.json()["error"]) == (401, "bad_signature")
    assert ledger(pay) == []


# --------------------------------------------------------------------------- field binding


@pytest.mark.parametrize(
    "changes",
    [
        {"amount_paise": 485001},
        {"amount_paise": 4850000},
        {"payee_account": "EVE-777"},
        {"payee_account": "acme-4410-2291"},  # exact match only, no normalisation at the payment rail
        {"payee_account": "ACME-4410-2291 "},
        {"invoice_id": "INV-1052"},
    ],
)
def test_payment_not_matching_pass_is_403(pay: TestClient, changes: dict[str, Any]) -> None:
    r = pay.post("/pay", json=body(fresh_pass(), **changes))
    assert (r.status_code, r.json()["error"]) == (403, "field_mismatch")
    assert ledger(pay) == []


def test_float_amount_is_rejected(pay: TestClient) -> None:
    assert pay.post("/pay", json=body(fresh_pass(), amount_paise=485000.0)).status_code == 422


def test_mismatch_does_not_burn_the_pass(pay: TestClient) -> None:
    p = fresh_pass()
    assert pay.post("/pay", json=body(p, payee_account="EVE-777")).status_code == 403
    assert pay.post("/pay", json=body(p)).status_code == 200


# --------------------------------------------------------------------------- expiry & replay


def test_expired_pass_is_401(pay: TestClient) -> None:
    p = fresh_pass(now=utc_now() - timedelta(seconds=121))
    r = pay.post("/pay", json=body(p))
    assert (r.status_code, r.json()["error"]) == (401, "expired")
    assert ledger(pay) == []


def test_replay_is_409(pay: TestClient) -> None:
    p = fresh_pass()
    assert pay.post("/pay", json=body(p)).status_code == 200
    r = pay.post("/pay", json=body(p))
    assert (r.status_code, r.json()["error"]) == (409, "replay")
    assert len(ledger(pay)) == 1


def test_reset_clears_ledger_but_never_unburns_nonces(pay: TestClient) -> None:
    p = fresh_pass()
    assert pay.post("/pay", json=body(p)).status_code == 200
    assert pay.post("/reset").status_code == 200
    assert ledger(pay) == []
    assert pay.post("/pay", json=body(p)).status_code == 409


def test_concurrent_replay_pays_exactly_once(pay: TestClient, env: Env) -> None:
    """The nonce burn is atomic: 16 simultaneous attempts with one pass → one payment."""
    req = PayRequest.model_validate(body(fresh_pass()))
    results: list[str] = []
    barrier = threading.Barrier(16)

    def attempt() -> None:
        conn = db.connect(env.pay_db)
        try:
            barrier.wait()
            verify_and_pay(conn, req, key=TEST_KEY, now=datetime.now(UTC))
            results.append("paid")
        except PayError as e:
            results.append(e.error)
        finally:
            conn.close()

    threads = [threading.Thread(target=attempt) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("paid") == 1
    assert results.count("replay") == 15
    assert len(ledger(pay)) == 1
