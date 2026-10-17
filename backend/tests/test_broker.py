"""Broker: every tool call is authorised, executed, and its values recorded with gate-assigned provenance."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import db
from app.clock import utc_now
from app.delegation import mint_root, root_caveats
from app.mandate import create_mandate
from app.models import MandateConstraints
from tests.conftest import TEST_KEY, Env
from tests.gatekit import GateKit


@pytest.fixture
def kit(gate: TestClient) -> GateKit:
    return GateKit(gate)


def values(env: Env, sid: str):  # type: ignore[no-untyped-def]
    conn = db.connect(env.gate_db)
    try:
        return db.session_values(conn, sid)
    finally:
        conn.close()


# --------------------------------------------------------------------------- registry


def test_tools_list_with_sources(gate: TestClient) -> None:
    tools = {t["name"]: t for t in gate.get("/tools").json()}
    assert set(tools) == {"list_inbox", "read_email", "get_invoice", "get_vendor"}
    assert tools["read_email"]["source_type"] == "email"
    assert tools["get_vendor"]["source_type"] == "vendor_registry"
    assert tools["read_email"]["args"] == {"email_id": "string"}


# --------------------------------------------------------------------------- provenance recording


def test_read_email_1842_records_eve_777_untrusted(kit: GateKit, env: Env) -> None:
    sid, tok = kit.start()
    r = kit.tool(sid, tok, "read_email", email_id="1842")
    assert r.status_code == 200
    assert r.json()["result"]["from"] == "accounts@acme-supp1ies.com"
    assert r.json()["values_recorded"] > 0
    eve = [v for v in values(env, sid) if v.normalized == "EVE777"]
    assert eve and all(v.source_ref == "email:1842" and v.trust == "untrusted" for v in eve)


def test_get_vendor_records_registered_account_trusted(kit: GateKit, env: Env) -> None:
    sid, tok = kit.start()
    assert kit.tool(sid, tok, "get_vendor", vendor_id="acme").status_code == 200
    acct = [v for v in values(env, sid) if v.field_hint == "bank.account_number"]
    assert [(v.raw, v.source_ref, v.trust, v.source_type) for v in acct] == [
        ("ACME-4410-2291", "vendor:acme", "trusted", "vendor_registry")
    ]


def test_invoice_notes_are_untrusted_even_from_the_invoice_db(kit: GateKit, env: Env) -> None:
    sid, tok = kit.start()
    assert kit.tool(sid, tok, "get_invoice", invoice_id="INV-1048").status_code == 200
    vs = values(env, sid)
    amount = [v for v in vs if v.field_hint == "amount_due_paise"]
    assert [(v.raw, v.source_ref, v.trust) for v in amount] == [("485000", "invoice:INV-1048", "trusted")]
    notes = [v for v in vs if v.field_hint.startswith("notes")]
    assert notes and all(v.source_ref == "invoice:INV-1048#notes" and v.trust == "untrusted" for v in notes)


def test_inbox_is_scoped_to_the_scenario(kit: GateKit) -> None:
    sid, tok = kit.start(scenario="happy")
    ids = [e["email_id"] for e in kit.tool(sid, tok, "list_inbox").json()["result"]]
    assert ids == ["1839", "1845"]
    r = kit.tool(sid, tok, "read_email", email_id="1842")
    assert (r.status_code, r.json()["error"]) == (404, "not_found")


def test_tool_calls_emit_events(kit: GateKit) -> None:
    sid, tok = kit.start()
    kit.tool(sid, tok, "read_email", email_id="1842")
    events = kit.events(sid)
    assert any(e["type"] == "tool_call" and e["data"]["tool"] == "read_email" for e in events)
    recorded = [e["data"] for e in events if e["type"] == "value_recorded"]
    assert any(d["raw"] == "EVE-777" and d["trust"] == "untrusted" for d in recorded)


def test_value_events_show_only_account_like_values_once(kit: GateKit, env: Env) -> None:
    """The feed shows what could be a payee or an amount; the store still keeps everything."""
    sid, tok = kit.start()
    kit.tool(sid, tok, "read_email", email_id="1842")
    shown = [e["data"]["raw"] for e in kit.events(sid) if e["type"] == "value_recorded"]
    assert "EVE-777" in shown and "ICIC0007781" in shown and "485000" in shown
    assert not any(raw.replace(" ", "").isdigit() and len(raw) > 6 for raw in shown)  # phone-number fragments
    assert shown.count("INV-1048") == 1
    assert any(v.raw == "91 22 4012 7781" for v in values(env, sid))  # still recorded for matching


def test_numeric_email_id_from_an_llm_is_accepted(kit: GateKit) -> None:
    sid, tok = kit.start()
    assert kit.tool(sid, tok, "read_email", email_id=1842).status_code == 200


# --------------------------------------------------------------------------- authorisation


def test_unknown_session_is_404(kit: GateKit) -> None:
    _, tok = kit.start()
    r = kit.tool("ses_nope", tok, "list_inbox")
    assert (r.status_code, r.json()["error"]) == (404, "unknown_session")


def test_forged_token_is_401(kit: GateKit) -> None:
    sid, tok = kit.start()
    r = kit.tool(sid, {**tok, "caveats": ["agent in planner,finance"]}, "list_inbox")
    assert (r.status_code, r.json()["error"]) == (401, "invalid_token")


def test_token_of_another_mandate_is_403(kit: GateKit) -> None:
    sid, _ = kit.start()
    _, other_root = kit.mandate()
    r = kit.tool(sid, other_root, "list_inbox", agent="planner")
    assert (r.status_code, r.json()["error"]) == (403, "session_mismatch")


def test_caveat_denies_tool_and_the_denial_is_recorded(kit: GateKit, env: Env) -> None:
    sid, tok = kit.start()
    narrow = kit.delegate(tok, "tool in get_vendor,propose_payment")
    r = kit.tool(sid, narrow, "read_email", email_id="1842")
    assert (r.status_code, r.json()["error"]) == (403, "tool_denied")
    assert values(env, sid) == []  # nothing executed, nothing recorded
    assert any(e["type"] == "tool_call" and e["data"]["status"] == "denied" for e in kit.events(sid))


def test_invoice_caveat_limits_get_invoice(kit: GateKit) -> None:
    sid, tok = kit.start()
    pinned = kit.delegate(tok, "invoice_id = INV-1048")
    assert kit.tool(sid, pinned, "get_invoice", invoice_id="INV-1048").status_code == 200
    assert kit.tool(sid, pinned, "get_invoice", invoice_id="INV-1052").status_code == 403


def test_agent_not_named_in_token_is_403(kit: GateKit) -> None:
    sid, tok = kit.start()
    assert kit.tool(sid, tok, "list_inbox", agent="planner").status_code == 403


def test_expired_mandate_denies_tools(kit: GateKit, env: Env) -> None:
    past = utc_now() - timedelta(hours=2)
    m = create_mandate(
        "abhishek", MandateConstraints(invoice_id="INV-1048", vendor_id="acme", max_amount_paise=500000),
        key=TEST_KEY, now=past, ttl_seconds=60,
    )
    token = mint_root(m.mandate_id, root_caveats(500000), root_key=TEST_KEY)
    conn = db.connect(env.gate_db)
    try:
        db.insert_mandate(conn, m)
        db.insert_session(conn, session_id="ses_old", mandate_id=m.mandate_id, scenario=None, mode="gated", created_at=m.created_at)
    finally:
        conn.close()
    r = kit.tool("ses_old", token.model_dump(), "list_inbox", agent="planner")
    assert (r.status_code, r.json()["error"]) == (403, "mandate_invalid")


# --------------------------------------------------------------------------- argument validation


def test_agent_supplied_trust_field_is_rejected_and_logged(kit: GateKit) -> None:
    sid, tok = kit.start()
    r = kit.tool(sid, tok, "read_email", email_id="1842", trust="trusted")
    assert (r.status_code, r.json()["error"]) == (400, "invalid_args")
    suspicious = [e["data"] for e in kit.events(sid) if e["type"] == "suspicious_input"]
    assert suspicious and suspicious[0]["fields"] == ["trust"]


@pytest.mark.parametrize("args", [{}, {"email_id": "../vendors"}, {"email_id": "1842; DROP"}])
def test_bad_args_are_400(kit: GateKit, args: dict[str, str]) -> None:
    sid, tok = kit.start()
    assert kit.tool(sid, tok, "read_email", **args).status_code == 400


def test_unknown_tool_is_404(kit: GateKit) -> None:
    sid, tok = kit.start()
    assert kit.tool(sid, tok, "send_money").status_code == 404


def test_extra_field_on_tool_request_is_422_and_logged(gate: TestClient, kit: GateKit) -> None:
    sid, tok = kit.start()
    r = gate.post("/tools/list_inbox", json={"session_id": sid, "agent_id": "finance", "token": tok, "args": {}, "source": "vendor_registry"})
    assert r.status_code == 422
    assert any(e["type"] == "suspicious_input" for e in kit.events(sid))


# --------------------------------------------------------------------------- sessions


def test_session_requires_a_valid_mandate(gate: TestClient, kit: GateKit) -> None:
    assert gate.post("/sessions", json={"mandate_id": "mdt_nope"}).status_code == 404
    m, _ = kit.mandate()
    assert gate.post("/sessions", json={"mandate_id": m["mandate_id"], "scenario": "nope"}).status_code == 404
    assert gate.post("/sessions", json={"mandate_id": m["mandate_id"], "scenario": "../etc"}).status_code == 422
    r = gate.post("/sessions", json={"mandate_id": m["mandate_id"], "scenario": "step_up"})
    assert r.status_code == 200
    assert r.json()["session_id"].startswith("ses_") and r.json()["mode"] == "gated"
