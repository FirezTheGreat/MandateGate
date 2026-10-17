"""mandate.py + POST /mandates: the signed record of what the human authorised."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import db
from app.crypto import sign
from app.delegation import root_caveats, verify_chain
from app.mandate import create_mandate, mandate_payload, verify_mandate
from app.models import DelegationToken, Mandate, MandateConstraints
from tests.conftest import TEST_KEY, Env

NOW = datetime(2026, 10, 17, 9, 0, 0, tzinfo=UTC)
CONSTRAINTS = MandateConstraints(invoice_id="INV-1048", vendor_id="acme", max_amount_paise=500000)


def make() -> Mandate:
    return create_mandate("abhishek", CONSTRAINTS, key=TEST_KEY, now=NOW, ttl_seconds=3600)


def with_constraint(**changes: object) -> Callable[[Mandate], Mandate]:
    return lambda m: m.model_copy(update={"constraints": m.constraints.model_copy(update=changes)})


def test_fresh_mandate_verifies() -> None:
    m = make()
    assert m.mandate_id.startswith("mdt_")
    assert m.created_at == "2026-10-17T09:00:00Z" and m.expires_at == "2026-10-17T10:00:00Z"
    assert verify_mandate(m, key=TEST_KEY, now=NOW).ok


@pytest.mark.parametrize(
    "tamper",
    [
        lambda m: m.model_copy(update={"principal": "eve"}),
        lambda m: m.model_copy(update={"mandate_id": "mdt_other"}),
        lambda m: m.model_copy(update={"created_at": "2026-10-17T08:00:00Z"}),
        lambda m: m.model_copy(update={"expires_at": "2027-10-17T10:00:00Z"}),
        lambda m: m.model_copy(update={"action": "send_email"}),
        with_constraint(invoice_id="INV-9999"),
        with_constraint(vendor_id="eve"),
        with_constraint(max_amount_paise=10_000_000),
        with_constraint(currency="USD"),
        with_constraint(payee_source="email"),
        lambda m: m.model_copy(update={"signature": "0" * 64}),
        lambda m: m.model_copy(update={"signature": m.signature[:-1] + ("0" if m.signature[-1] != "0" else "1")}),
    ],
    ids=[
        "principal", "mandate_id", "created_at", "expires_at", "action",
        "invoice_id", "vendor_id", "max_amount", "currency", "payee_source",
        "zero_sig", "flipped_sig",
    ],
)
def test_tampering_any_field_breaks_verification(tamper: Callable[[Mandate], Mandate]) -> None:
    verdict = verify_mandate(tamper(make()), key=TEST_KEY, now=NOW)
    assert not verdict.ok
    assert "signature" in verdict.detail


def test_wrong_key_fails() -> None:
    assert not verify_mandate(make(), key="cd" * 32, now=NOW).ok


def test_expired_mandate_fails() -> None:
    m = make()
    assert verify_mandate(m, key=TEST_KEY, now=NOW + timedelta(seconds=3599)).ok
    verdict = verify_mandate(m, key=TEST_KEY, now=NOW + timedelta(seconds=3600))
    assert not verdict.ok and "expired" in verdict.detail


def test_unparseable_expiry_fails_closed_even_if_signed() -> None:
    m = make().model_copy(update={"expires_at": "soon"})
    m = m.model_copy(update={"signature": sign(TEST_KEY, mandate_payload(m))})
    assert not verify_mandate(m, key=TEST_KEY, now=NOW).ok


@pytest.mark.parametrize("ttl", [0, -1])
def test_non_positive_ttl_refused(ttl: int) -> None:
    with pytest.raises(ValueError):
        create_mandate("abhishek", CONSTRAINTS, key=TEST_KEY, now=NOW, ttl_seconds=ttl)


# --------------------------------------------------------------------------- POST /mandates

BODY = {"principal": "abhishek", "constraints": CONSTRAINTS.model_dump(), "ttl_seconds": 3600}


def test_post_mandates_returns_signed_mandate_and_root_token(gate: TestClient, env: Env) -> None:
    r = gate.post("/mandates", json=BODY)
    assert r.status_code == 200
    mandate = Mandate.model_validate(r.json()["mandate"])
    token = r.json()["token"]
    now = datetime.now(UTC)
    assert verify_mandate(mandate, key=TEST_KEY, now=now).ok
    assert token["mandate_id"] == mandate.mandate_id
    assert token["caveats"] == root_caveats(500000)
    assert token["parent_token_id"] is None
    assert verify_chain(DelegationToken.model_validate(token), root_key=TEST_KEY).ok

    conn = db.connect(env.gate_db)
    try:
        assert db.get_mandate(conn, mandate.mandate_id) == mandate
        assert db.get_token(conn, token["token_id"]) is not None
    finally:
        conn.close()


def test_post_mandates_mints_unique_ids(gate: TestClient) -> None:
    a, b = gate.post("/mandates", json=BODY).json(), gate.post("/mandates", json=BODY).json()
    assert a["mandate"]["mandate_id"] != b["mandate"]["mandate_id"]
    assert a["token"]["token_id"] != b["token"]["token_id"]


def test_post_mandates_rejects_float_amount(gate: TestClient) -> None:
    bad = {**BODY, "constraints": {**BODY["constraints"], "max_amount_paise": 5000.0}}
    assert gate.post("/mandates", json=bad).status_code == 422
