"""delegation.py + POST /delegate: macaroon-style tokens that can only narrow authority."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.delegation import (
    CaveatError,
    EvalContext,
    amount_limit,
    attenuate,
    detect_escalation,
    evaluate,
    mint_root,
    parse_caveat,
    root_caveats,
    verify_chain,
)
from app.models import DelegationToken
from tests.conftest import TEST_KEY

NOW = datetime(2026, 10, 17, 9, 0, 0, tzinfo=UTC)
ROOT_CAVEATS = root_caveats(500000)


def root() -> DelegationToken:
    return mint_root("mdt_example", ROOT_CAVEATS, root_key=TEST_KEY)


def finance() -> DelegationToken:
    return attenuate(root(), ["agent = finance"])


def ctx(agent: str = "finance", tool: str = "propose_payment", invoice_id: str | None = "INV-1048") -> EvalContext:
    return EvalContext(agent=agent, tool=tool, invoice_id=invoice_id, now=NOW)


# --------------------------------------------------------------------------- minting & chain verification


def test_root_caveats_match_contract() -> None:
    assert ROOT_CAVEATS == [
        "agent in planner,finance",
        "tool in list_inbox,read_email,get_invoice,get_vendor,propose_payment",
        "max_amount_paise <= 500000",
    ]


def test_root_token_verifies() -> None:
    t = root()
    assert t.token_id.startswith("tok_") and t.parent_token_id is None
    assert verify_chain(t, root_key=TEST_KEY).ok


def test_attenuated_token_verifies_without_root_key() -> None:
    parent = root()
    child = attenuate(parent, ["agent = finance"])  # note: no key passed
    assert child.caveats == [*ROOT_CAVEATS, "agent = finance"]
    assert child.parent_token_id == parent.token_id and child.token_id != parent.token_id
    assert verify_chain(child, root_key=TEST_KEY).ok


def test_multi_hop_attenuation_verifies() -> None:
    t = attenuate(finance(), ["tool in get_vendor,propose_payment", "invoice_id = INV-1048"])
    assert verify_chain(t, root_key=TEST_KEY).ok


@pytest.mark.parametrize("index", range(4))
def test_removing_any_caveat_breaks_chain(index: int) -> None:
    t = finance()
    stripped = t.model_copy(update={"caveats": [c for i, c in enumerate(t.caveats) if i != index]})
    assert not verify_chain(stripped, root_key=TEST_KEY).ok


@pytest.mark.parametrize(
    "index,replacement",
    [(0, "agent in planner,finance,eve"), (1, "tool in propose_payment"), (2, "max_amount_paise <= 1000000"), (3, "agent = eve")],
)
def test_editing_any_caveat_breaks_chain(index: int, replacement: str) -> None:
    t = finance()
    caveats = list(t.caveats)
    caveats[index] = replacement
    assert not verify_chain(t.model_copy(update={"caveats": caveats}), root_key=TEST_KEY).ok


def test_reordering_caveats_breaks_chain() -> None:
    t = finance()
    assert not verify_chain(t.model_copy(update={"caveats": list(reversed(t.caveats))}), root_key=TEST_KEY).ok


def test_appending_without_resigning_breaks_chain() -> None:
    t = finance()
    assert not verify_chain(t.model_copy(update={"caveats": [*t.caveats, "agent = eve"]}), root_key=TEST_KEY).ok


def test_rebinding_to_another_mandate_breaks_chain() -> None:
    assert not verify_chain(finance().model_copy(update={"mandate_id": "mdt_other"}), root_key=TEST_KEY).ok


def test_wrong_root_key_fails() -> None:
    assert not verify_chain(finance(), root_key="cd" * 32).ok


@pytest.mark.parametrize("sig", ["", "0" * 64, "not-hex", "é" * 64])
def test_garbage_signature_fails_without_raising(sig: str) -> None:
    assert not verify_chain(finance().model_copy(update={"sig": sig}), root_key=TEST_KEY).ok


def test_attenuate_rejects_malformed_caveat() -> None:
    with pytest.raises(CaveatError):
        attenuate(root(), ["agent=finance"])


# --------------------------------------------------------------------------- strict parser / evaluate

MALFORMED = [
    "",
    "agent=finance",
    "agent = finance ",
    " agent = finance",
    "agent  = finance",
    "Agent = finance",
    "аgent = finance",  # Cyrillic 'а'
    "agent = ",
    "agent in finance,",
    "agent in ,finance",
    "agent in finance, planner",
    "agent != finance",
    "tool == propose_payment",
    "max_amount_paise <= 4850.5",
    "max_amount_paise <= -1",
    "max_amount_paise <= 0500",
    "max_amount_paise <= 1e6",
    "max_amount_paise < 500000",
    "max_amount_paise >= 500000",
    "invoice_id = INV 1048",
    "expires_before 2026-10-17",
    "expires_before 2026-10-17T10:00:00",
    "expires_before tomorrow",
    "vendor_id = acme",
    "payee_account = EVE-777",
    "trust = trusted",
    "x" * 300,
]


@pytest.mark.parametrize("caveat", MALFORMED)
def test_unknown_or_malformed_caveat_fails_closed(caveat: str) -> None:
    with pytest.raises(CaveatError):
        parse_caveat(caveat)
    verdict = evaluate([*ROOT_CAVEATS, caveat], ctx())
    assert not verdict.ok
    assert "caveat" in verdict.detail


def test_all_caveats_hold() -> None:
    assert evaluate(finance().caveats, ctx()).ok


@pytest.mark.parametrize(
    "context",
    [ctx(agent="planner"), ctx(agent="eve"), ctx(tool="send_email"), ctx(tool="pay")],
    ids=["planner_not_finance", "unknown_agent", "tool_not_listed", "tool_not_listed_2"],
)
def test_violated_caveat_fails(context: EvalContext) -> None:
    assert not evaluate(finance().caveats, context).ok


def test_invoice_caveat() -> None:
    caveats = [*finance().caveats, "invoice_id = INV-1048"]
    assert evaluate(caveats, ctx(invoice_id="INV-1048")).ok
    assert not evaluate(caveats, ctx(invoice_id="INV-9999")).ok
    # an action that references no invoice (e.g. list_inbox) is not restricted by it
    assert evaluate(caveats, ctx(tool="list_inbox", invoice_id=None)).ok


def test_expires_before_caveat() -> None:
    assert evaluate(["expires_before 2026-10-17T09:00:01Z"], ctx()).ok
    assert not evaluate(["expires_before 2026-10-17T09:00:00Z"], ctx()).ok
    assert not evaluate(["expires_before 2026-10-17T08:00:00Z"], ctx()).ok


def test_evaluate_reports_every_failing_caveat() -> None:
    verdict = evaluate(["agent = planner", "tool = get_vendor"], ctx())
    assert "agent = planner" in verdict.detail and "tool = get_vendor" in verdict.detail


def test_evaluate_leaves_amount_to_amount_limit() -> None:
    """Amount caveats feed the step-up check, so evaluate() never fails on them."""
    assert evaluate(["max_amount_paise <= 1"], ctx()).ok


# --------------------------------------------------------------------------- amount limit & escalation


def test_amount_limit_is_tightest_bound() -> None:
    assert amount_limit(ROOT_CAVEATS) == 500000
    assert amount_limit([*ROOT_CAVEATS, "max_amount_paise <= 300000"]) == 300000
    assert amount_limit(["agent = finance"]) is None


def test_looser_amount_caveat_has_no_effect_and_is_flagged() -> None:
    escalated = attenuate(finance(), ["max_amount_paise <= 1000000"])
    assert verify_chain(escalated, root_key=TEST_KEY).ok  # a valid token...
    assert amount_limit(escalated.caveats) == 500000  # ...that still enforces the original bound
    assert detect_escalation(escalated.caveats) == ["max_amount_paise <= 1000000"]


def test_tighter_or_equal_amount_is_not_escalation() -> None:
    assert detect_escalation([*ROOT_CAVEATS, "max_amount_paise <= 500000", "max_amount_paise <= 1"]) == []


def test_widening_a_set_caveat_is_flagged() -> None:
    caveats = [*ROOT_CAVEATS, "agent = finance", "agent in finance,eve", "tool in propose_payment,send_money"]
    assert detect_escalation(caveats) == ["agent in finance,eve", "tool in propose_payment,send_money"]


def test_narrowing_a_set_caveat_is_not_escalation() -> None:
    assert detect_escalation([*ROOT_CAVEATS, "agent = finance", "tool in get_vendor,propose_payment"]) == []


def test_amount_limit_raises_on_malformed() -> None:
    with pytest.raises(CaveatError):
        amount_limit(["max_amount_paise <= lots"])


# --------------------------------------------------------------------------- POST /delegate


def test_post_delegate_attenuates(gate: TestClient) -> None:
    root_token = gate.post(
        "/mandates",
        json={"principal": "abhishek", "constraints": {"invoice_id": "INV-1048", "vendor_id": "acme", "max_amount_paise": 500000}},
    ).json()["token"]
    r = gate.post("/delegate", json={"token": root_token, "caveats": ["agent = finance"]})
    assert r.status_code == 200
    child = DelegationToken.model_validate(r.json())
    assert child.caveats == [*root_token["caveats"], "agent = finance"]
    assert child.parent_token_id == root_token["token_id"]
    assert verify_chain(child, root_key=TEST_KEY).ok


def test_post_delegate_rejects_malformed_caveat(gate: TestClient) -> None:
    r = gate.post("/delegate", json={"token": root().model_dump(), "caveats": ["agent=finance"]})
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_caveat"


def test_post_delegate_rejects_forged_token(gate: TestClient) -> None:
    forged = root().model_copy(update={"caveats": ["max_amount_paise <= 99999999"]})
    r = gate.post("/delegate", json={"token": forged.model_dump(), "caveats": ["agent = finance"]})
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_token"
