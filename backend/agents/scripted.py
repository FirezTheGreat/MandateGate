"""Scripted finance agent: the same tool calls as the LLM agent, decided by fixed rules, no LLM.

Used as the fallback when the network or API is unavailable, and for fast deterministic tests.
It behaves like a busy clerk: it reads the inbox, and a bank-change notice it finds there wins
over the vendor master. That makes it fall for business-email compromise the way the hero
attack needs, through the gate's tools rather than through hard-coded answers.
"""

import re
from collections.abc import Callable
from typing import Any

from agents.finance import AgentRun, make_executor
from agents.gate_client import GateClient

ACCOUNT_LINE = re.compile(r"account\s*(?:number|no\.?)\s*[:\-]\s*([^\n]+)", re.IGNORECASE)


class ScriptError(RuntimeError):
    pass


def run(
    client: GateClient, *, session_id: str, token: dict[str, Any], invoice_id: str, vendor_id: str,
    log: Callable[[str], None] = print,
) -> AgentRun:
    execute = make_executor(client, session_id=session_id, token=token)
    steps = 0

    def call(name: str, **args: Any) -> Any:
        nonlocal steps
        steps += 1
        log(f"[scripted] step {steps} -> {name} {args}")
        content, is_error, raw = execute(name, args)
        log(f"[scripted] step {steps} <- {'ERROR ' if is_error else ''}{content[:160]}")
        if is_error:
            raise ScriptError(content)
        return raw

    try:
        inbox = call("list_inbox")
        accounts: list[str] = []
        for item in inbox:
            email = call("read_email", email_id=item["email_id"])
            accounts += [m.group(1).strip() for m in ACCOUNT_LINE.finditer(email["body"])]
        invoice = call("get_invoice", invoice_id=invoice_id)
        vendor = call("get_vendor", vendor_id=vendor_id)
        payee = accounts[-1] if accounts else vendor["bank"]["account_number"]
        decision = call(
            "propose_payment", invoice_id=invoice_id, vendor_id=vendor_id, payee_account=payee,
            amount_paise=invoice["amount_due_paise"], memo=f"Paying {invoice_id}",
        )
    except ScriptError as e:
        return AgentRun(decision=None, steps=steps, stopped="error", note=str(e))
    return AgentRun(decision=decision, steps=steps, stopped="proposed")
