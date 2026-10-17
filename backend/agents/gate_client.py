"""HTTP client for the gate and the payment service: the agents' ONLY way in.

Agents live in the untrusted zone and never import from backend/app/ (a test enforces it).
Responses are plain JSON dicts shaped like the contracts in CLAUDE.md §6.
"""

import os
from typing import Any

import httpx


class GateError(Exception):
    """A structured `{error, detail}` failure from the gate or payment service (status 0 = unreachable)."""

    def __init__(self, status: int, error: str, detail: str) -> None:
        super().__init__(f"{status} {error}: {detail}")
        self.status, self.error, self.detail = status, error, detail


class GateClient:
    def __init__(self, gate: httpx.Client, pay: httpx.Client) -> None:
        self.gate, self.pay_http = gate, pay

    @classmethod
    def from_env(cls) -> "GateClient":
        return cls(
            httpx.Client(base_url=os.environ.get("GATE_URL", "http://127.0.0.1:8000"), timeout=30),
            httpx.Client(base_url=os.environ.get("PAY_URL", "http://127.0.0.1:8001"), timeout=30),
        )

    def close(self) -> None:
        self.gate.close()
        self.pay_http.close()

    @staticmethod
    def _call(http: httpx.Client, method: str, path: str, body: Any = None) -> Any:
        try:
            r = http.request(method, path, json=body)
        except httpx.HTTPError as e:
            raise GateError(0, "unreachable", f"{type(e).__name__} calling {path}; is `make dev` running?") from e
        if r.status_code < 400:
            return r.json()
        try:
            err = r.json()
        except ValueError:
            err = {}
        raise GateError(r.status_code, str(err.get("error", "http_error")), str(err.get("detail", r.text[:200])))

    # ------------------------------------------------------------------ human / dashboard side

    def set_mode(self, mode: str) -> None:
        self._call(self.gate, "POST", "/admin/mode", {"mode": mode})

    def create_mandate(self, principal: str, constraints: dict[str, Any], ttl_seconds: int = 3600) -> dict[str, Any]:
        """→ {"mandate": {...}, "token": {...root token...}}"""
        return self._call(self.gate, "POST", "/mandates", {"principal": principal, "constraints": constraints, "ttl_seconds": ttl_seconds})

    def create_session(self, mandate_id: str, scenario: str | None) -> dict[str, Any]:
        return self._call(self.gate, "POST", "/sessions", {"mandate_id": mandate_id, "scenario": scenario})

    def get_decision(self, decision_id: str) -> dict[str, Any]:
        return self._call(self.gate, "GET", f"/decisions/{decision_id}")

    def approve(self, decision_id: str, approve: bool) -> dict[str, Any]:
        return self._call(self.gate, "POST", f"/approvals/{decision_id}", {"approve": approve})

    def reset(self) -> None:
        self._call(self.gate, "POST", "/admin/reset")
        self._call(self.pay_http, "POST", "/reset")

    # ------------------------------------------------------------------ agent side

    def delegate(self, token: dict[str, Any], caveats: list[str]) -> dict[str, Any]:
        return self._call(self.gate, "POST", "/delegate", {"token": token, "caveats": caveats})

    def call_tool(self, session_id: str, agent_id: str, token: dict[str, Any], name: str, args: dict[str, Any]) -> Any:
        """Run a brokered tool and return its `result` (the gate records provenance on the way)."""
        body = {"session_id": session_id, "agent_id": agent_id, "token": token, "args": args}
        return self._call(self.gate, "POST", f"/tools/{name}", body)["result"]

    def propose(
        self, *, session_id: str, token: dict[str, Any], agent_id: str, invoice_id: str, vendor_id: str,
        payee_account: str, amount_paise: int, memo: str = "", currency: str = "INR",
    ) -> dict[str, Any]:
        """propose_payment → Decision (with `one_pass` on ALLOW)."""
        body = {
            "session_id": session_id, "token": token, "agent_id": agent_id, "invoice_id": invoice_id,
            "vendor_id": vendor_id, "payee_account": payee_account, "amount_paise": amount_paise,
            "currency": currency, "memo": memo,
        }
        return self._call(self.gate, "POST", "/proposals", body)

    # ------------------------------------------------------------------ payment rail

    def pay(self, one_pass: dict[str, Any]) -> dict[str, Any]:
        """Execute exactly the payment the pass was issued for. → Receipt."""
        payment = {k: one_pass[k] for k in ("invoice_id", "payee_account", "amount_paise", "currency")}
        return self._call(self.pay_http, "POST", "/pay", {"one_pass": one_pass, "payment": payment})

    def ledger(self) -> list[dict[str, Any]]:
        return self._call(self.pay_http, "GET", "/ledger")
