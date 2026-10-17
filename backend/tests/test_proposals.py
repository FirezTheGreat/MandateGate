"""POST /proposals end to end: decisions, passes, step-up approvals, baseline mode, fail closed.

Phase 2 acceptance criteria are marked [A].
"""

import pytest
from fastapi.testclient import TestClient

from app import db, policy
from tests.conftest import Env
from tests.gatekit import GateKit, pay_body


@pytest.fixture
def kit(gate: TestClient) -> GateKit:
    return GateKit(gate)


def check(decision: dict, name: str) -> dict:  # type: ignore[type-arg]
    return next(c for c in decision["checks"] if c["check"] == name)


# --------------------------------------------------------------------------- the demo flows


def test_happy_path_allows_and_the_pass_pays(kit: GateKit, pay: TestClient) -> None:
    """[A] payee ACME-4410-2291 after get_vendor(acme) → ALLOW + pass."""
    sid, tok = kit.start("happy")
    kit.investigate(sid, tok, emails=("1839",))
    d = kit.propose(sid, tok, "ACME-4410-2291").json()
    assert d["outcome"] == "ALLOW"
    p = d["one_pass"]
    assert (p["payee_account"], p["amount_paise"], p["decision_id"]) == ("ACME-4410-2291", 485000, d["decision_id"])
    r = pay.post("/pay", json=pay_body(p))
    assert r.status_code == 200, r.text
    assert [row["payee_account"] for row in pay.get("/ledger").json()] == ["ACME-4410-2291"]


def test_hero_attack_is_blocked_with_the_source_named(kit: GateKit) -> None:
    """[A] payee EVE-777 → BLOCK, payee_provenance.found == ["email:1842 (untrusted)"]."""
    sid, tok = kit.start()
    kit.investigate(sid, tok)
    d = kit.propose(sid, tok, "EVE-777").json()
    assert d["outcome"] == "BLOCK" and d["one_pass"] is None
    payee = check(d, "payee_provenance")
    assert payee["status"] == "fail"
    assert payee["required"] == "vendor_registry:acme"
    assert payee["found"] == ["email:1842 (untrusted)"]


def test_same_attack_in_baseline_mode_pays_the_attacker(gate: TestClient, kit: GateKit, pay: TestClient) -> None:
    """[A] the EVE-777 proposal in baseline mode → ALLOW (intentional, for the demo)."""
    assert gate.post("/admin/mode", json={"mode": "baseline"}).json() == {"mode": "baseline"}
    sid, tok = kit.start()
    kit.investigate(sid, tok)
    d = kit.propose(sid, tok, "EVE-777").json()
    assert d["outcome"] == "ALLOW" and d["mode"] == "baseline"
    assert check(d, "payee_provenance")["status"] == "skipped"
    assert pay.post("/pay", json=pay_body(d["one_pass"])).status_code == 200
    assert pay.get("/ledger").json()[0]["payee_account"] == "EVE-777"


def test_never_seen_payee_is_unknown_origin(kit: GateKit) -> None:
    """[A] a payee seen nowhere → BLOCK "unknown origin"."""
    sid, tok = kit.start()
    kit.investigate(sid, tok)
    payee = check(kit.propose(sid, tok, "ZZZZ-0000-1111").json(), "payee_provenance")
    assert payee["status"] == "fail" and "unknown origin" in payee["detail"]


def test_wrong_amount_blocks_on_amount_provenance(kit: GateKit) -> None:
    """[A] 499000 for INV-1048 → BLOCK on amount_provenance."""
    sid, tok = kit.start()
    kit.investigate(sid, tok)
    d = kit.propose(sid, tok, "ACME-4410-2291", amount=499000).json()
    assert d["outcome"] == "BLOCK"
    assert check(d, "amount_provenance")["status"] == "fail"


def test_over_limit_steps_up_and_approval_pays(gate: TestClient, kit: GateKit, pay: TestClient) -> None:
    """[A] INV-1052 at 520000 with a valid payee → STEP_UP; the human approves → pass → paid."""
    sid, tok = kit.start("step_up", invoice="INV-1052")
    kit.investigate(sid, tok, emails=(), invoice="INV-1052")
    d = kit.propose(sid, tok, "ACME-4410-2291", amount=520000, invoice="INV-1052").json()
    assert d["outcome"] == "STEP_UP" and d["one_pass"] is None

    pending = gate.get("/approvals").json()
    assert [(a["decision_id"], a["amount_paise"], a["max_amount_paise"]) for a in pending] == [(d["decision_id"], 520000, 500000)]

    approved = gate.post(f"/approvals/{d['decision_id']}", json={"approve": True}).json()
    assert approved["outcome"] == "ALLOW" and approved["one_pass"]["amount_paise"] == 520000
    assert check(approved, "amount_within_limit")["status"] == "pass"
    assert pay.post("/pay", json=pay_body(approved["one_pass"])).status_code == 200

    assert gate.get("/approvals").json() == []
    again = gate.post(f"/approvals/{d['decision_id']}", json={"approve": True})
    assert (again.status_code, again.json()["error"]) == (409, "already_resolved")
    assert gate.get(f"/decisions/{d['decision_id']}").json()["outcome"] == "ALLOW"


def test_denied_step_up_is_blocked(gate: TestClient, kit: GateKit) -> None:
    sid, tok = kit.start("step_up", invoice="INV-1052")
    kit.investigate(sid, tok, emails=(), invoice="INV-1052")
    d = kit.propose(sid, tok, "ACME-4410-2291", amount=520000, invoice="INV-1052").json()
    denied = gate.post(f"/approvals/{d['decision_id']}", json={"approve": False}).json()
    assert denied["outcome"] == "BLOCK" and denied["one_pass"] is None
    assert gate.get(f"/decisions/{d['decision_id']}").json()["outcome"] == "BLOCK"


def test_only_step_ups_can_be_approved(gate: TestClient, kit: GateKit) -> None:
    sid, tok = kit.start()
    kit.investigate(sid, tok)
    d = kit.propose(sid, tok, "EVE-777").json()
    r = gate.post(f"/approvals/{d['decision_id']}", json={"approve": True})
    assert r.status_code == 404


# --------------------------------------------------------------------------- hostile input


def test_smuggled_trust_field_is_422_and_logged(kit: GateKit) -> None:
    """[A] extra field "trusted": true → 422 and a suspicious_input event."""
    sid, tok = kit.start()
    r = kit.propose(sid, tok, "EVE-777", trusted=True)
    assert r.status_code == 422
    suspicious = [e["data"] for e in kit.events(sid) if e["type"] == "suspicious_input"]
    assert suspicious and suspicious[0]["fields"] == ["trusted"] and suspicious[0]["path"] == "/proposals"


def test_proposal_on_unknown_session_blocks(kit: GateKit) -> None:
    _, tok = kit.start()
    d = kit.propose("ses_nope", tok, "ACME-4410-2291").json()
    assert d["outcome"] == "BLOCK" and "unknown session" in check(d, "mandate_valid")["detail"]


def test_escalation_attempt_is_logged_but_powerless(kit: GateKit, env: Env) -> None:
    sid, tok = kit.start("step_up", invoice="INV-1052")
    widened = kit.delegate(tok, "max_amount_paise <= 9000000")
    kit.investigate(sid, widened, emails=(), invoice="INV-1052")
    d = kit.propose(sid, widened, "ACME-4410-2291", amount=520000, invoice="INV-1052").json()
    assert d["outcome"] == "STEP_UP"  # the looser cap changed nothing
    assert any(e["type"] == "escalation_attempt" for e in kit.events(sid))
    conn = db.connect(env.gate_db)
    try:  # the /delegate call itself was flagged too (no session yet)
        assert any(e.type == "escalation_attempt" and e.session_id is None for e in db.list_events(conn, None))
    finally:
        conn.close()


# --------------------------------------------------------------------------- fail closed


def test_decision_engine_crash_blocks(kit: GateKit, monkeypatch: pytest.MonkeyPatch) -> None:
    sid, tok = kit.start("happy")
    kit.investigate(sid, tok, emails=())

    def boom(*_a, **_k):  # type: ignore[no-untyped-def]
        raise RuntimeError("bug")

    monkeypatch.setattr(policy, "decide", boom)
    r = kit.propose(sid, tok, "ACME-4410-2291")
    assert r.status_code == 200
    assert r.json()["outcome"] == "BLOCK" and r.json()["one_pass"] is None
    assert "Traceback" not in r.text and "bug" not in r.text


def test_persistence_failure_after_allow_returns_block_without_pass(kit: GateKit, monkeypatch: pytest.MonkeyPatch) -> None:
    sid, tok = kit.start("happy")
    kit.investigate(sid, tok, emails=())

    def boom(*_a, **_k):  # type: ignore[no-untyped-def]
        raise RuntimeError("disk full")

    monkeypatch.setattr(db, "insert_pass", boom)
    d = kit.propose(sid, tok, "ACME-4410-2291").json()
    assert d["outcome"] == "BLOCK" and d["one_pass"] is None


# --------------------------------------------------------------------------- history, events, admin


def test_decisions_are_persisted_and_listed(gate: TestClient, kit: GateKit) -> None:
    sid, tok = kit.start()
    kit.investigate(sid, tok)
    d = kit.propose(sid, tok, "EVE-777").json()
    assert gate.get(f"/decisions/{d['decision_id']}").json() == d
    assert gate.get("/decisions").json()[0]["decision_id"] == d["decision_id"]
    types = [e["type"] for e in kit.events(sid)]
    assert types.index("proposal") < types.index("decision")
    assert "token" not in gate.get("/decisions").text  # bearer tokens never echoed back


def test_mode_is_readable(gate: TestClient) -> None:
    assert gate.get("/admin/mode").json() == {"mode": "gated"}


def test_reset_wipes_gate_state(gate: TestClient, kit: GateKit) -> None:
    sid, tok = kit.start()
    kit.investigate(sid, tok)
    kit.propose(sid, tok, "EVE-777")
    assert gate.post("/admin/reset").json()["ok"] is True
    assert gate.get("/decisions").json() == []
    assert kit.tool(sid, tok, "list_inbox").status_code == 404  # session gone
