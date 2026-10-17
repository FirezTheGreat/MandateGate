"""tracer: rebuild how each critical value reached the proposal. Phase 4 acceptance marked [A]."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from agents import run_scenario
from agents.gate_client import GateClient
from app.models import TraceGraph
from tests.gatekit import GateKit


@pytest.fixture
def client(gate: TestClient, pay: TestClient) -> GateClient:
    return GateClient(gate, pay)


def trace_for(gate: TestClient, decision_id: str) -> TraceGraph:
    r = gate.get(f"/trace/{decision_id}")
    assert r.status_code == 200, r.text
    return TraceGraph.model_validate(r.json())


def scenario_trace(client: GateClient, gate: TestClient, scenario: str, mode: str, **kw: Any) -> TraceGraph:
    r = run_scenario.run(scenario, mode, "scripted", client=client, log=lambda _: None, **kw)
    return trace_for(gate, r["decision_id"])


def node(t: TraceGraph, ref: str):  # type: ignore[no-untyped-def]
    return next(n for n in t.nodes if n.data.ref == ref)


def edge(t: TraceGraph, source: str, target: str):  # type: ignore[no-untyped-def]
    return next(e for e in t.edges if e.source == source and e.target == target)


def kind(t: TraceGraph, type_: str):  # type: ignore[no-untyped-def]
    return next(n for n in t.nodes if n.type == type_)


# --------------------------------------------------------------------------- the hero BLOCK


def test_hero_block_trace_shows_the_bad_path(client: GateClient, gate: TestClient) -> None:
    """[A] email:1842 → finance:read_email → proposal(EVE-777) → BLOCK, all bad; vendor registry path good."""
    t = scenario_trace(client, gate, "hero_attack", "gated")
    email, vendor = node(t, "email:1842"), node(t, "vendor:acme")
    read = next(n for n in t.nodes if n.type == "tool_call" and n.data.label == "finance: read_email #1842")
    proposal, decision = kind(t, "proposal"), kind(t, "decision")

    assert (email.data.status, email.data.trust) == ("bad", "untrusted")
    assert read.data.status == "bad"
    assert edge(t, email.id, read.id).data.status == "bad"
    payee_edge = next(e for e in t.edges if (e.source, e.target, e.data.field) == (read.id, proposal.id, "payee_account"))
    assert (payee_edge.data.status, payee_edge.data.field, payee_edge.data.value) == ("bad", "payee_account", "EVE-777")
    assert proposal.data.status == "bad" and "EVE-777" in proposal.data.label
    assert (decision.data.label, decision.data.status) == ("BLOCK", "bad")
    assert edge(t, proposal.id, decision.id).data.status == "bad"

    get_vendor = next(n for n in t.nodes if n.type == "tool_call" and n.data.label == "finance: get_vendor acme")
    assert (vendor.data.status, vendor.data.trust) == ("good", "trusted")
    assert get_vendor.data.status == "good" and edge(t, vendor.id, get_vendor.id).data.status == "good"


def test_hero_trace_lists_where_each_critical_value_came_from(client: GateClient, gate: TestClient) -> None:
    t = scenario_trace(client, gate, "hero_attack", "gated")
    fields = {f.field: f for f in t.fields}
    assert (fields["payee_account"].value, fields["payee_account"].status) == ("EVE-777", "bad")
    assert fields["payee_account"].sources == ["email:1842 (untrusted)"]
    assert fields["amount_paise"].status == "good" and "invoice:INV-1048 (trusted)" in fields["amount_paise"].sources


def test_decisions_now_have_traces(client: GateClient, gate: TestClient) -> None:
    r = run_scenario.run("hero_attack", "gated", "scripted", client=client, log=lambda _: None)
    assert gate.get(f"/decisions/{r['decision_id']}").json()["trace_available"] is True


# --------------------------------------------------------------------------- other outcomes


def test_baseline_payment_to_the_attacker_is_traced_as_bad(client: GateClient, gate: TestClient) -> None:
    t = scenario_trace(client, gate, "hero_attack", "baseline")
    decision = kind(t, "decision")
    assert (decision.data.label, decision.data.status) == ("ALLOW", "bad")
    assert "provenance not checked" in (decision.data.detail or "")
    assert node(t, "email:1842").data.status == "bad"


def test_happy_trace_is_all_good(client: GateClient, gate: TestClient) -> None:
    t = scenario_trace(client, gate, "happy", "gated")
    assert kind(t, "decision").data.status == "good"
    assert all(f.status == "good" for f in t.fields)
    assert all(e.data.status != "bad" for e in t.edges)
    assert node(t, "email:1839").data.status == "neutral"  # read, but fed nothing critical


def test_step_up_trace_is_amber(client: GateClient, gate: TestClient) -> None:
    t = scenario_trace(client, gate, "step_up", "gated", approval_timeout_s=0)
    assert (kind(t, "decision").data.label, kind(t, "decision").data.status) == ("STEP_UP", "warn")


def test_reformatted_value_is_still_traced_to_its_source(gate: TestClient) -> None:
    """[A] the agent rewrote the account as 'E V E 777': the trace still finds Email #1842."""
    kit = GateKit(gate)
    sid, tok = kit.start()
    kit.investigate(sid, tok)
    d = kit.propose(sid, tok, "E V E 777").json()
    t = trace_for(gate, d["decision_id"])
    fields = {f.field: f for f in t.fields}
    assert fields["payee_account"].sources == ["email:1842 (untrusted)"]
    assert node(t, "email:1842").data.status == "bad"


def test_never_seen_payee_traces_to_nothing(gate: TestClient) -> None:
    kit = GateKit(gate)
    sid, tok = kit.start()
    kit.investigate(sid, tok)
    d = kit.propose(sid, tok, "ZZZZ-0000-1111").json()
    t = trace_for(gate, d["decision_id"])
    payee = next(f for f in t.fields if f.field == "payee_account")
    assert (payee.status, payee.sources) == ("bad", [])
    assert not any(e.data.field == "payee_account" for e in t.edges)


# --------------------------------------------------------------------------- shape


def test_trace_is_react_flow_shaped_with_fixed_columns(client: GateClient, gate: TestClient) -> None:
    t = scenario_trace(client, gate, "hero_attack", "gated")
    ids = [n.id for n in t.nodes]
    assert len(ids) == len(set(ids))
    assert all(e.source in ids and e.target in ids for e in t.edges)
    columns = {"source": 0, "tool_call": 1, "proposal": 2, "decision": 3}
    assert all(n.position.x == columns[n.type] * 280 for n in t.nodes)


def test_unknown_decision_has_no_trace(gate: TestClient) -> None:
    r = gate.get("/trace/dec_nope")
    assert (r.status_code, r.json()["error"]) == (404, "not_found")
