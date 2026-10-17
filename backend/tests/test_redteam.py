"""Phase 7 red-team findings, each pinned by a test (ROADMAP Phase 7). Plus guards for the classes of
bug the red-team prompt asks about, so they cannot creep back in.

F1  Host / Origin: a web page in the operator's browser must not reach the demo endpoints
    (cross-site POST to body-less routes, DNS rebinding to everything).
F2  Money is bounded (no SQLite overflow → 500 after a human approves a huge baseline payment).
F3  Identifiers are bounded (no 1 MB payee stored and streamed; no unusable mandates).
F4  /delegate refuses chains that could never verify.
F5  Payment-event signatures use a key derived for that purpose, not the pass key itself.
"""

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.crypto import derive_key, sign
from app.models import MAX_PAISE
from payment_service.notify import SIGNATURE_HEADER
from tests.conftest import TEST_KEY
from tests.gatekit import GateKit

BACKEND = Path(__file__).resolve().parent.parent
EVIL = "https://evil.example"
DASHBOARD = "http://localhost:5173"


@pytest.fixture
def kit(gate: TestClient) -> GateKit:
    return GateKit(gate)


# --------------------------------------------------------------------------- F1 Host / Origin


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8000", "192.168.1.50:8000"])
def test_gate_refuses_foreign_host_headers(gate: TestClient, host: str) -> None:
    """DNS rebinding: the page's origin resolves to 127.0.0.1 but keeps its own Host header."""
    for r in (gate.get("/decisions", headers={"Host": host}), gate.post("/admin/mode", json={"mode": "baseline"}, headers={"Host": host})):
        assert (r.status_code, r.json()["error"]) == (400, "bad_host")
    assert gate.get("/admin/mode").json() == {"mode": "gated"}


def test_payment_service_refuses_foreign_host_headers(pay: TestClient) -> None:
    r = pay.get("/ledger", headers={"Host": "evil.example:8001"})
    assert (r.status_code, r.json()["error"]) == (400, "bad_host")


@pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1:8000", "localhost"])
def test_local_host_headers_work(gate: TestClient, host: str) -> None:
    assert gate.get("/admin/mode", headers={"Host": host}).status_code == 200


def test_cross_site_post_is_refused(gate: TestClient, pay: TestClient, kit: GateKit) -> None:
    """A form POST from any website can reach body-less routes like /admin/reset (CORS only hides the response)."""
    m, _ = kit.mandate()
    for client, path in ((gate, "/admin/reset"), (pay, "/reset")):
        r = client.post(path, headers={"Origin": EVIL})
        assert (r.status_code, r.json()["error"]) == (403, "bad_origin")
    assert gate.get(f"/mandates/{m['mandate_id']}").status_code == 200  # nothing was wiped


def test_dashboard_and_non_browser_posts_still_work(gate: TestClient, pay: TestClient) -> None:
    assert gate.post("/admin/mode", json={"mode": "gated"}, headers={"Origin": DASHBOARD}).status_code == 200
    assert gate.post("/admin/mode", json={"mode": "gated"}).status_code == 200  # agents and scripts send no Origin
    assert pay.post("/reset", headers={"Origin": DASHBOARD}).status_code == 200


def test_cross_site_reads_are_not_blocked_by_origin(gate: TestClient) -> None:
    """GETs are safe methods: CORS decides whether the browser may read them."""
    r = gate.get("/admin/mode", headers={"Origin": EVIL})
    assert r.status_code == 200 and "access-control-allow-origin" not in r.headers


# --------------------------------------------------------------------------- F2 money bounds


def test_mandate_cap_above_the_bound_is_a_422_not_a_500(gate: TestClient) -> None:
    for cap in (MAX_PAISE + 1, 10**17, 2**64):
        r = gate.post("/mandates", json={"principal": "abhishek", "constraints": {"invoice_id": "INV-1048", "vendor_id": "acme", "max_amount_paise": cap}})
        assert r.status_code == 422, cap
    assert gate.post("/mandates", json={"principal": "abhishek", "constraints": {"invoice_id": "INV-1048", "vendor_id": "acme", "max_amount_paise": MAX_PAISE}}).status_code == 200


def test_proposal_amount_above_the_bound_is_rejected(kit: GateKit) -> None:
    sid, tok = kit.start()
    for amount in (MAX_PAISE + 1, 2**63, 2**70):
        assert kit.propose(sid, tok, "ACME-4410-2291", amount=amount).status_code == 422


def test_payment_amount_above_the_bound_is_rejected(pay: TestClient) -> None:
    payment = {"invoice_id": "INV-1048", "payee_account": "ACME-4410-2291", "amount_paise": 2**63, "currency": "INR"}
    assert pay.post("/pay", json={"one_pass": None, "payment": payment}).status_code == 422


# --------------------------------------------------------------------------- F3 identifier bounds


@pytest.mark.parametrize(
    "field,value", [("payee_account", "A" * 1_000_000), ("payee_account", ""), ("invoice_id", "I" * 10_000), ("agent_id", "f" * 10_000)],
    ids=["payee-1MB", "payee-empty", "invoice-10k", "agent-10k"],
)
def test_proposal_identifiers_are_bounded(kit: GateKit, field: str, value: str) -> None:
    sid, tok = kit.start()
    body = {"session_id": sid, "token": tok, "agent_id": "finance", "invoice_id": "INV-1048", "vendor_id": "acme",
            "payee_account": "ACME-4410-2291", "amount_paise": 485000, "currency": "INR", field: value}
    assert kit.c.post("/proposals", json=body).status_code == 422


def test_odd_but_bounded_proposals_still_get_a_recorded_block(kit: GateKit) -> None:
    """Bounds are about size, not judgement: a strange invoice id is still decided (and shown) as BLOCK."""
    sid, tok = kit.start()
    kit.investigate(sid, tok)
    r = kit.propose(sid, tok, "ACME-4410-2291", invoice="INV 9999 (pay today)")
    assert r.status_code == 200 and r.json()["outcome"] == "BLOCK"


@pytest.mark.parametrize("constraints,principal", [
    ({"invoice_id": "INV 1048\n", "vendor_id": "acme"}, "abhishek"),
    ({"invoice_id": "INV-1048", "vendor_id": "Acme Supplies"}, "abhishek"),
    ({"invoice_id": "INV-1048", "vendor_id": "acme"}, ""),
])
def test_mandates_must_be_expressible_as_caveats(gate: TestClient, constraints: dict[str, str], principal: str) -> None:
    """The planner narrows with `invoice_id = X`; a mandate whose ids the caveat grammar cannot express is useless."""
    r = gate.post("/mandates", json={"principal": principal, "constraints": {**constraints, "max_amount_paise": 500000}})
    assert r.status_code == 422


def test_unexpected_arg_names_are_truncated_in_events(kit: GateKit) -> None:
    sid, tok = kit.start()
    kit.tool(sid, tok, "list_inbox", **{"x" * 10_000: 1})
    flagged = [e["data"]["fields"] for e in kit.events(sid) if e["type"] == "suspicious_input"]
    assert flagged and all(len(f) <= 64 for fields in flagged for f in fields)


# --------------------------------------------------------------------------- F4 chain length


def test_delegate_refuses_a_chain_that_could_never_verify(kit: GateKit) -> None:
    _, root = kit.mandate()
    r = kit.c.post("/delegate", json={"token": root, "caveats": ["agent = finance"] * 62})
    assert (r.status_code, r.json()["error"]) == (400, "invalid_caveat")
    assert kit.c.post("/delegate", json={"token": root, "caveats": ["agent = finance"] * 61}).status_code == 200  # 3 + 61 = 64


# --------------------------------------------------------------------------- F5 key separation


def _report() -> dict[str, object]:
    from app.clock import to_iso, utc_now

    return {"status": "refused", "sent_at": to_iso(utc_now()), "error": "missing_pass", "detail": "x",
            "receipt": None, "pass_id": None, "decision_id": None, "payee_account": "EVE-777", "amount_paise": 485000}


def test_payment_events_need_the_derived_event_key(gate: TestClient) -> None:
    body = _report()
    r = gate.post("/internal/payment-event", json=body, headers={SIGNATURE_HEADER: sign(TEST_KEY, body)})
    assert (r.status_code, r.json()["error"]) == (401, "bad_signature")  # the raw pass key is not the event key
    r = gate.post("/internal/payment-event", json=body, headers={SIGNATURE_HEADER: sign(derive_key(TEST_KEY, "payment-event"), body)})
    assert r.status_code == 200


def test_derived_keys_differ_per_purpose() -> None:
    assert derive_key(TEST_KEY, "payment-event") not in (TEST_KEY, derive_key(TEST_KEY, "other"))
    assert len(derive_key(TEST_KEY, "payment-event")) == 64


# --------------------------------------------------------------------------- guards (red-team prompt)


SECRET_NAMES = ("sig", "signature", "nonce", "mac", "digest")  # plus any *_key (mandate_key, pass_key, ...)


def _secretish(node: ast.AST) -> bool:
    name = node.attr if isinstance(node, ast.Attribute) else node.id if isinstance(node, ast.Name) else ""
    return name.endswith("_key") or any(name == s or name.endswith("_" + s) for s in SECRET_NAMES)


def test_no_plain_equality_on_secrets() -> None:
    """§2.9: signatures, nonces and keys are compared only with hmac.compare_digest."""
    offenders = []
    for path in [*(BACKEND / "app").rglob("*.py"), *(BACKEND / "payment_service").rglob("*.py")]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Compare) and any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops):
                if any(_secretish(n) for n in [node.left, *node.comparators]):
                    offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


def test_trusted_code_never_reads_trust_from_input() -> None:
    """§2.2: no request model carries a trust/provenance field the gate could be tempted to read."""
    from app import models

    inbound = [models.PaymentProposal, models.ToolCallRequest, models.DelegateRequest, models.SessionCreateRequest, models.PayRequest]
    for m in inbound:
        assert not {"trust", "trusted", "source", "source_type", "provenance", "tag", "tags"} & set(m.model_fields), m.__name__
