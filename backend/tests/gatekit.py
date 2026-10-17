"""Test helper that drives the gate over HTTP the way the Phase 3 agents will."""

from typing import Any

from fastapi.testclient import TestClient
from httpx import Response


class GateKit:
    def __init__(self, client: TestClient) -> None:
        self.c = client

    def mandate(self, invoice: str = "INV-1048", max_amount: int = 500000) -> tuple[dict[str, Any], dict[str, Any]]:
        r = self.c.post(
            "/mandates",
            json={"principal": "abhishek", "constraints": {"invoice_id": invoice, "vendor_id": "acme", "max_amount_paise": max_amount}},
        )
        assert r.status_code == 200, r.text
        return r.json()["mandate"], r.json()["token"]

    def session(self, mandate_id: str, scenario: str | None = "hero_attack") -> str:
        r = self.c.post("/sessions", json={"mandate_id": mandate_id, "scenario": scenario})
        assert r.status_code == 200, r.text
        return r.json()["session_id"]

    def delegate(self, token: dict[str, Any], *caveats: str) -> dict[str, Any]:
        r = self.c.post("/delegate", json={"token": token, "caveats": list(caveats)})
        assert r.status_code == 200, r.text
        return r.json()

    def start(self, scenario: str = "hero_attack", invoice: str = "INV-1048", max_amount: int = 500000) -> tuple[str, dict[str, Any]]:
        """Mandate → session → finance token, as the planner would hand it over."""
        m, root = self.mandate(invoice, max_amount)
        return self.session(m["mandate_id"], scenario), self.delegate(root, "agent = finance")

    def tool(self, sid: str, token: dict[str, Any], name: str, agent: str = "finance", **args: Any) -> Response:
        return self.c.post(f"/tools/{name}", json={"session_id": sid, "agent_id": agent, "token": token, "args": args})

    def investigate(self, sid: str, token: dict[str, Any], emails: tuple[str, ...] = ("1839", "1842"), invoice: str = "INV-1048") -> None:
        """The hero tool sequence: inbox, emails, invoice, vendor."""
        assert self.tool(sid, token, "list_inbox").status_code == 200
        for e in emails:
            assert self.tool(sid, token, "read_email", email_id=e).status_code == 200
        assert self.tool(sid, token, "get_invoice", invoice_id=invoice).status_code == 200
        assert self.tool(sid, token, "get_vendor", vendor_id="acme").status_code == 200

    def propose(
        self, sid: str, token: dict[str, Any], payee: str, amount: int = 485000, invoice: str = "INV-1048", **extra: Any
    ) -> Response:
        body = {
            "session_id": sid, "token": token, "agent_id": "finance", "invoice_id": invoice, "vendor_id": "acme",
            "payee_account": payee, "amount_paise": amount, "currency": "INR", "memo": "test", **extra,
        }
        return self.c.post("/proposals", json=body)

    def events(self, sid: str) -> list[dict[str, Any]]:
        r = self.c.get(f"/sessions/{sid}/events")
        assert r.status_code == 200, r.text
        return r.json()


def pay_body(one_pass: dict[str, Any]) -> dict[str, Any]:
    payment = {k: one_pass[k] for k in ("invoice_id", "payee_account", "amount_paise", "currency")}
    return {"one_pass": one_pass, "payment": payment}
