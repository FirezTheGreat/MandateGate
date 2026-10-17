"""Scripted finance agent: the same tool calls as the LLM agent, decided by fixed rules, no LLM.

Used as the fallback when the network or API is unavailable, for fast deterministic tests, and
as the "simulated fooled agent" in the demo and the attack suite. It behaves like a busy clerk
who trusts the latest message about the invoice being paid:

  - reads every inbox email, the invoice (including its notes), and the vendor record;
  - follows links found in messages about this invoice (fetch_page);
  - a bank-account line in those messages wins over the vendor master;
  - a "revised/corrected/updated amount" line wins over the invoice amount;
  - "pay INV-x instead" switches the invoice.

So it falls for content attacks through the gate's tools, not through hard-coded answers.
Messages that do not mention the invoice being paid (another vendor's bill) are ignored.
"""

import re
from collections.abc import Callable
from typing import Any

from agents.finance import AgentRun, make_executor
from agents.gate_client import GateClient

ACCOUNT_LINE = re.compile(r"account\s*(?:number|no\.?)\s*[:\-]\s*([^\n,]+)", re.IGNORECASE)
REVISED_AMOUNT = re.compile(r"(?:revised|corrected|updated)\s+amount[^\n:]*:\s*(?:rs\.?|₹|inr)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.IGNORECASE)
SWAP_INVOICE = re.compile(r"pay\s+(INV-[0-9A-Za-z-]+)\s+instead", re.IGNORECASE)
URL = re.compile(r"https?://[^\s)>\"']+")


class ScriptError(RuntimeError):
    pass


def rupees_to_paise(text: str) -> int:
    whole, _, frac = text.replace(",", "").partition(".")
    return int(whole) * 100 + int((frac or "0").ljust(2, "0")[:2])


def run(
    client: GateClient, *, session_id: str, token: dict[str, Any], invoice_id: str, vendor_id: str,
    payee_override: str | None = None, log: Callable[[str], None] = print,
) -> AgentRun:
    execute = make_executor(client, session_id=session_id, token=token)
    steps = 0

    def call(name: str, required: bool = True, **args: Any) -> Any:
        nonlocal steps
        steps += 1
        log(f"[scripted] step {steps} -> {name} {args}")
        content, is_error, raw = execute(name, args)
        log(f"[scripted] step {steps} <- {'ERROR ' if is_error else ''}{content[:160]}")
        if is_error and required:
            raise ScriptError(content)
        return None if is_error else raw

    try:
        relevant: list[str] = []  # texts about this invoice, in reading order
        links: list[str] = []
        for item in call("list_inbox"):
            email = call("read_email", email_id=item["email_id"])
            text = f"{email['subject']}\n{email['body']}"
            if invoice_id.lower() in text.lower():
                relevant.append(text)
                links += URL.findall(email["body"])
        invoice = call("get_invoice", invoice_id=invoice_id)
        if invoice.get("notes"):
            relevant.append(invoice["notes"])
        vendor = call("get_vendor", vendor_id=vendor_id)
        for url in dict.fromkeys(links):
            page = call("fetch_page", required=False, url=url)
            if page and invoice_id.lower() in page["body"].lower():
                relevant.append(page["body"])

        accounts = [m.group(1).strip() for t in relevant for m in ACCOUNT_LINE.finditer(t)]
        amounts = [rupees_to_paise(m.group(1)) for t in relevant for m in REVISED_AMOUNT.finditer(t)]
        swaps = [m.group(1) for t in relevant for m in SWAP_INVOICE.finditer(t)]
        payee = payee_override or (accounts[-1] if accounts else vendor["bank"]["account_number"])
        amount = amounts[-1] if amounts else invoice["amount_due_paise"]
        pay_invoice = swaps[-1] if swaps else invoice_id
        decision = call(
            "propose_payment", invoice_id=pay_invoice, vendor_id=vendor_id, payee_account=payee,
            amount_paise=amount, memo=f"Paying {pay_invoice}",
        )
    except ScriptError as e:
        return AgentRun(decision=None, steps=steps, stopped="error", note=str(e))
    return AgentRun(decision=decision, steps=steps, stopped="proposed")
