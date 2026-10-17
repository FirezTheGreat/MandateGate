"""passes.py: one-time passes, issued only for ALLOW decisions and bound to exact fields."""

import re
from datetime import UTC, datetime, timedelta

import pytest

from app.crypto import verify
from app.models import CHECK_ORDER, CheckResult, Decision, ProposalSummary
from app.passes import issue_pass, pass_payload
from tests.conftest import TEST_KEY

NOW = datetime(2026, 10, 17, 9, 0, 0, tzinfo=UTC)


def decision(outcome: str = "ALLOW", mandate_id: str | None = "mdt_example") -> Decision:
    return Decision(
        decision_id="dec_test",
        session_id="ses_test",
        mandate_id=mandate_id,
        mode="gated",
        created_at="2026-10-17T09:00:00Z",
        proposal=ProposalSummary(
            agent_id="finance",
            invoice_id="INV-1048",
            vendor_id="acme",
            payee_account="ACME-4410-2291",
            amount_paise=485000,
            currency="INR",
        ),
        outcome=outcome,  # type: ignore[arg-type]
        checks=[CheckResult(check=c, status="pass") for c in CHECK_ORDER],
        trace_available=True,
    )


def test_pass_binds_exact_proposal_fields() -> None:
    p = issue_pass(decision(), key=TEST_KEY, now=NOW, ttl_seconds=120)
    assert p.pass_id.startswith("pas_")
    assert (p.decision_id, p.mandate_id) == ("dec_test", "mdt_example")
    assert (p.invoice_id, p.payee_account, p.amount_paise, p.currency) == ("INV-1048", "ACME-4410-2291", 485000, "INR")
    assert p.exp == "2026-10-17T09:02:00Z"
    assert re.fullmatch(r"[0-9a-f]{32}", p.nonce)


def test_pass_signature_verifies_and_covers_every_field() -> None:
    p = issue_pass(decision(), key=TEST_KEY, now=NOW, ttl_seconds=120)
    assert verify(TEST_KEY, pass_payload(p), p.sig)
    assert "sig" not in pass_payload(p)
    for field, value in [("amount_paise", 1), ("payee_account", "EVE-777"), ("exp", "2099-01-01T00:00:00Z"), ("nonce", "0" * 32)]:
        assert not verify(TEST_KEY, pass_payload(p.model_copy(update={field: value})), p.sig), field


def test_each_pass_is_unique() -> None:
    a = issue_pass(decision(), key=TEST_KEY, now=NOW, ttl_seconds=120)
    b = issue_pass(decision(), key=TEST_KEY, now=NOW, ttl_seconds=120)
    assert a.nonce != b.nonce and a.pass_id != b.pass_id


@pytest.mark.parametrize("outcome", ["BLOCK", "STEP_UP"])
def test_refuses_to_issue_for_non_allow(outcome: str) -> None:
    with pytest.raises(ValueError):
        issue_pass(decision(outcome), key=TEST_KEY, now=NOW, ttl_seconds=120)


def test_refuses_without_mandate() -> None:
    with pytest.raises(ValueError):
        issue_pass(decision(mandate_id=None), key=TEST_KEY, now=NOW, ttl_seconds=120)


@pytest.mark.parametrize("ttl", [0, -5, 601])
def test_refuses_bad_ttl(ttl: int) -> None:
    with pytest.raises(ValueError):
        issue_pass(decision(), key=TEST_KEY, now=NOW, ttl_seconds=ttl)


def test_custom_ttl() -> None:
    p = issue_pass(decision(), key=TEST_KEY, now=NOW, ttl_seconds=30)
    assert p.exp == (NOW + timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
