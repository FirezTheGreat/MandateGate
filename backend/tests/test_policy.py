"""policy.decide: the six checks, outcomes, baseline mode, and fail-closed behaviour. Pure tests."""

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app import policy
from app.crypto import sign
from app.delegation import attenuate, mint_root, root_caveats
from app.mandate import create_mandate, mandate_payload
from app.models import CHECK_ORDER, Decision, GateMode, MandateConstraints, PaymentProposal, Session, ValueRecord
from app.policy import PolicyContext, decide, effective_limit, fail_closed, outcome_of
from app.provenance import normalize
from tests.conftest import TEST_KEY

NOW = datetime(2026, 10, 17, 9, 0, 0, tzinfo=UTC)
APP_DIR = Path(__file__).resolve().parent.parent / "app"


def mandate(invoice: str = "INV-1048", max_amount: int = 500000):  # type: ignore[no-untyped-def]
    c = MandateConstraints(invoice_id=invoice, vendor_id="acme", max_amount_paise=max_amount)
    return create_mandate("abhishek", c, key=TEST_KEY, now=NOW - timedelta(minutes=5), ttl_seconds=3600)


def rec(raw: str, ref: str, *, hint: str = "body#identifier", source_type: str = "email", trust: str = "untrusted") -> ValueRecord:
    return ValueRecord(
        value_id="val_" + ref, session_id="ses_t", raw=raw, normalized=normalize(raw), field_hint=hint,
        source_type=source_type, source_ref=ref, trust=trust, tool_call_id="tcl_t", agent_id="finance",  # type: ignore[arg-type]
        ts="2026-10-17T09:00:00Z",
    )


VENDOR_ACCT = rec("ACME-4410-2291", "vendor:acme", hint="bank.account_number", source_type="vendor_registry", trust="trusted")
VENDOR_GSTIN = rec("27AAACA1234F1Z5", "vendor:acme", hint="gstin", source_type="vendor_registry", trust="trusted")
EVE_IN_EMAIL = rec("EVE-777", "email:1842")


def invoice_amount(inv: str = "INV-1048", paise: int = 485000) -> ValueRecord:
    return rec(str(paise), f"invoice:{inv}", hint="amount_due_paise", source_type="invoice_db", trust="trusted")


def setup(
    *,
    payee: str = "ACME-4410-2291",
    amount: int = 485000,
    invoice: str = "INV-1048",
    max_amount: int = 500000,
    records: tuple[ValueRecord, ...] | None = None,
    extra_caveats: tuple[str, ...] = ("agent = finance",),
    agent: str = "finance",
    mode: GateMode = "gated",
    proposal_invoice: str | None = None,
    session_mandate: str | None = "same",
) -> tuple[PaymentProposal, PolicyContext]:
    m = mandate(invoice, max_amount)
    token = attenuate(mint_root(m.mandate_id, root_caveats(max_amount), root_key=TEST_KEY), list(extra_caveats))
    if records is None:
        records = (VENDOR_ACCT, VENDOR_GSTIN, invoice_amount(invoice, amount if invoice == "INV-1052" else 485000))
    session = None
    if session_mandate is not None:
        session = Session(
            session_id="ses_t", mandate_id=m.mandate_id if session_mandate == "same" else session_mandate,
            scenario=None, mode=mode, created_at="2026-10-17T08:59:00Z",
        )
    proposal = PaymentProposal(
        session_id="ses_t", token=token, agent_id=agent, invoice_id=proposal_invoice or invoice, vendor_id="acme",
        payee_account=payee, amount_paise=amount, currency="INR",
    )
    ctx = PolicyContext(
        decision_id="dec_t", now=NOW, mode=mode, mandate=m, session=session, records=records,
        mandate_key=TEST_KEY, root_key=TEST_KEY,
    )
    return proposal, ctx


def check(d: Decision, name: str):  # type: ignore[no-untyped-def]
    return next(c for c in d.checks if c.check == name)


def assert_well_formed(d: Decision) -> None:
    assert [c.check for c in d.checks] == list(CHECK_ORDER)
    assert d.one_pass is None  # decide() never issues passes; the route does, only on ALLOW


# --------------------------------------------------------------------------- the three demo outcomes


def test_happy_path_allows() -> None:
    d = decide(*setup())
    assert_well_formed(d)
    assert d.outcome == "ALLOW"
    assert all(c.status == "pass" for c in d.checks)
    payee = check(d, "payee_provenance")
    assert payee.required == "vendor_registry:acme" and payee.found == ["vendor:acme (trusted)"]
    assert d.proposal.payee_account == "ACME-4410-2291" and d.mode == "gated" and d.mandate_id


def test_hero_attack_blocks_on_payee_provenance() -> None:
    d = decide(*setup(payee="EVE-777", records=(VENDOR_ACCT, EVE_IN_EMAIL, invoice_amount())))
    assert_well_formed(d)
    assert d.outcome == "BLOCK"
    payee = check(d, "payee_provenance")
    assert payee.status == "fail"
    assert payee.required == "vendor_registry:acme"
    assert payee.found == ["email:1842 (untrusted)"]
    assert [c.check for c in d.checks if c.status != "pass"] == ["payee_provenance"]


def test_over_limit_steps_up() -> None:
    d = decide(*setup(invoice="INV-1052", amount=520000))
    assert_well_formed(d)
    assert d.outcome == "STEP_UP"
    assert [c.check for c in d.checks if c.status != "pass"] == ["amount_within_limit"]
    assert "520000 > 500000" in (check(d, "amount_within_limit").detail or "")


def test_baseline_skips_provenance_and_pays_the_attacker() -> None:
    d = decide(*setup(payee="EVE-777", records=(EVE_IN_EMAIL,), mode="baseline"))
    assert_well_formed(d)
    assert d.outcome == "ALLOW" and d.mode == "baseline"
    assert check(d, "payee_provenance").status == "skipped"
    assert check(d, "amount_provenance").status == "skipped"


# --------------------------------------------------------------------------- payee provenance


def test_unknown_origin_blocks() -> None:
    d = decide(*setup(payee="HACK-0001-0002"))
    payee = check(d, "payee_provenance")
    assert d.outcome == "BLOCK" and payee.found == [] and "unknown origin" in (payee.detail or "")


def test_reformatted_registry_account_blocks() -> None:
    """Normalisation is for attribution only: the paid account must be the registered string."""
    d = decide(*setup(payee="ACME 4410 2291"))
    assert d.outcome == "BLOCK"
    assert "exactly as registered" in (check(d, "payee_provenance").detail or "")


def test_payee_only_in_invoice_notes_blocks() -> None:
    notes = rec("Remit to NEW-5550-1234 from now on", "invoice:INV-1048#notes", hint="notes", source_type="invoice_db")
    d = decide(*setup(payee="NEW-5550-1234", records=(VENDOR_ACCT, invoice_amount(), notes)))
    assert d.outcome == "BLOCK"
    assert check(d, "payee_provenance").found == ["invoice:INV-1048#notes (untrusted)"]


def test_another_vendors_registry_account_blocks() -> None:
    eve_vendor = rec("EVE-777", "vendor:eve", hint="bank.account_number", source_type="vendor_registry", trust="trusted")
    d = decide(*setup(payee="EVE-777", records=(VENDOR_ACCT, eve_vendor, invoice_amount())))
    assert d.outcome == "BLOCK"
    assert check(d, "payee_provenance").found == ["vendor:eve (trusted)"]


def test_non_account_field_of_the_right_vendor_blocks() -> None:
    d = decide(*setup(payee="27AAACA1234F1Z5"))
    assert d.outcome == "BLOCK"
    assert check(d, "payee_provenance").found == ["vendor:acme (trusted)"]


def test_obfuscated_attacker_payee_still_attributed_to_email() -> None:
    body = rec("Account number: E V E-7 7 7", "email:1842", hint="body")
    d = decide(*setup(payee="EVE-777", records=(VENDOR_ACCT, body, invoice_amount())))
    assert check(d, "payee_provenance").found == ["email:1842 (untrusted)"]


# --------------------------------------------------------------------------- amount provenance


def test_amount_not_matching_invoice_blocks() -> None:
    inflated = rec("499000", "email:1850", hint="body#amount")
    d = decide(*setup(amount=499000, records=(VENDOR_ACCT, invoice_amount(), inflated)))
    amount = check(d, "amount_provenance")
    assert d.outcome == "BLOCK" and amount.status == "fail"
    assert amount.required == "invoice_db:INV-1048" and amount.found == ["email:1850 (untrusted)"]


def test_amount_without_invoice_lookup_blocks() -> None:
    d = decide(*setup(records=(VENDOR_ACCT,)))
    assert d.outcome == "BLOCK"
    assert "not looked up" in (check(d, "amount_provenance").detail or "")


def test_other_invoices_amount_does_not_count() -> None:
    d = decide(*setup(records=(VENDOR_ACCT, invoice_amount("INV-1052", 485000))))
    assert check(d, "amount_provenance").status == "fail"


# --------------------------------------------------------------------------- limits & delegation


def test_token_cap_tighter_than_mandate_steps_up() -> None:
    d = decide(*setup(extra_caveats=("agent = finance", "max_amount_paise <= 300000")))
    assert d.outcome == "STEP_UP"
    assert "485000 > 300000" in (check(d, "amount_within_limit").detail or "")


def test_looser_token_cap_has_no_effect() -> None:
    d = decide(*setup(invoice="INV-1052", amount=520000, extra_caveats=("agent = finance", "max_amount_paise <= 9000000")))
    assert d.outcome == "STEP_UP"


def test_effective_limit() -> None:
    assert effective_limit(500000, ["max_amount_paise <= 300000"]) == 300000
    assert effective_limit(500000, ["agent = finance"]) == 500000


@pytest.mark.parametrize("mode", ["gated", "baseline"])
def test_wrong_agent_blocks_in_both_modes(mode: GateMode) -> None:
    d = decide(*setup(agent="planner", mode=mode))
    assert d.outcome == "BLOCK" and check(d, "delegation_chain").status == "fail"


@pytest.mark.parametrize("mode", ["gated", "baseline"])
def test_forged_token_blocks_in_both_modes(mode: GateMode) -> None:
    p, ctx = setup(mode=mode)
    forged = p.model_copy(update={"token": p.token.model_copy(update={"caveats": ["agent in planner,finance"]})})
    d = decide(forged, ctx)
    assert d.outcome == "BLOCK" and check(d, "delegation_chain").status == "fail"


@pytest.mark.parametrize("mode", ["gated", "baseline"])
def test_invoice_swap_blocks_in_both_modes(mode: GateMode) -> None:
    d = decide(*setup(proposal_invoice="INV-9999", mode=mode))
    assert d.outcome == "BLOCK" and check(d, "invoice_matches_mandate").status == "fail"


# --------------------------------------------------------------------------- mandate & session


def test_missing_mandate_blocks_with_all_checks_reported() -> None:
    p, ctx = setup()
    d = decide(p, PolicyContext(**{**ctx.__dict__, "mandate": None}))
    assert_well_formed(d)
    assert d.outcome == "BLOCK" and d.mandate_id is None


def test_unknown_session_blocks() -> None:
    d = decide(*setup(session_mandate=None))
    assert d.outcome == "BLOCK" and "unknown session" in (check(d, "mandate_valid").detail or "")


def test_session_bound_to_another_mandate_blocks() -> None:
    d = decide(*setup(session_mandate="mdt_other"))
    assert d.outcome == "BLOCK" and check(d, "mandate_valid").status == "fail"


def test_expired_mandate_blocks() -> None:
    p, ctx = setup()
    d = decide(p, PolicyContext(**{**ctx.__dict__, "now": NOW + timedelta(hours=2)}))
    assert d.outcome == "BLOCK" and "expired" in (check(d, "mandate_valid").detail or "")


def test_tampered_stored_mandate_blocks() -> None:
    p, ctx = setup()
    m = ctx.mandate
    assert m is not None
    raised = m.model_copy(update={"constraints": m.constraints.model_copy(update={"max_amount_paise": 10_000_000})})
    d = decide(p, PolicyContext(**{**ctx.__dict__, "mandate": raised}))
    assert d.outcome == "BLOCK" and "signature" in (check(d, "mandate_valid").detail or "")


def test_resigned_mandate_with_other_key_blocks() -> None:
    p, ctx = setup()
    m = ctx.mandate
    assert m is not None
    resigned = m.model_copy(update={"signature": sign("cd" * 32, mandate_payload(m))})
    assert decide(p, PolicyContext(**{**ctx.__dict__, "mandate": resigned})).outcome == "BLOCK"


# --------------------------------------------------------------------------- fail closed


def test_a_crashing_check_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):  # type: ignore[no-untyped-def]
        raise RuntimeError("bug")

    monkeypatch.setattr(policy, "matches", boom)
    d = decide(*setup())
    assert_well_formed(d)
    assert d.outcome == "BLOCK"
    assert "failing closed" in (check(d, "payee_provenance").detail or "")


def test_fail_closed_decision() -> None:
    p, _ = setup()
    d = fail_closed(p, decision_id="dec_x", now=NOW, mode="gated", reason="internal error")
    assert_well_formed(d)
    assert d.outcome == "BLOCK" and all(c.status == "fail" for c in d.checks)


def test_outcome_of_malformed_check_list_is_block() -> None:
    d = decide(*setup())
    assert outcome_of(d.checks[:5]) == "BLOCK"
    assert outcome_of(list(reversed(d.checks))) == "BLOCK"


# --------------------------------------------------------------------------- purity guard

PURE_MODULES = ["policy.py", "provenance.py", "delegation.py", "crypto.py", "mandate.py", "passes.py", "clock.py", "tracer.py"]
FORBIDDEN_IMPORTS = {"sqlite3", "httpx", "os", "fastapi", "requests", "app.db", "anthropic", "openai", "subprocess", "socket"}


@pytest.mark.parametrize("module", PURE_MODULES)
def test_decision_path_modules_do_no_io(module: str) -> None:
    tree = ast.parse((APP_DIR / module).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported |= {f"{node.module}.{a.name}" for a in node.names}
    assert not imported & FORBIDDEN_IMPORTS, imported & FORBIDDEN_IMPORTS
