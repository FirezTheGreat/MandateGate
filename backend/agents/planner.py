"""The planner: takes the human's instruction and the root token, narrows the token for the
finance agent, and hands the job over (CLAUDE.md §9).

Deterministic code, no LLM: narrowing authority is a fixed policy, and the agent that reads
untrusted content (and can be fooled by it) is the finance agent.
"""

from collections.abc import Callable
from typing import Any, Literal

from agents import finance, scripted
from agents.finance import AgentRun
from agents.gate_client import GateClient
from agents.llm import Conversation, make_conversation

FINANCE_TOOLS = "list_inbox,read_email,get_invoice,get_vendor,propose_payment"


def delegation_caveats(constraints: dict[str, Any]) -> list[str]:
    """Only the finance agent, only its tools, only this invoice, never more than the mandate."""
    return [
        "agent = finance",
        f"tool in {FINANCE_TOOLS}",
        f"invoice_id = {constraints['invoice_id']}",
        f"max_amount_paise <= {constraints['max_amount_paise']}",
    ]


def run(
    client: GateClient, *, instruction: str, root_token: dict[str, Any], constraints: dict[str, Any], session_id: str,
    agent: Literal["llm", "scripted"], conversation_factory: Callable[..., Conversation] = make_conversation,
    log: Callable[[str], None] = print,
) -> AgentRun:
    caveats = delegation_caveats(constraints)
    token = client.delegate(root_token, caveats)
    log(f"[planner] delegated to finance with: {'; '.join(caveats)}")
    if agent == "scripted":
        return scripted.run(
            client, session_id=session_id, token=token,
            invoice_id=constraints["invoice_id"], vendor_id=constraints["vendor_id"], log=log,
        )
    task = f"{instruction}\n\nInvoice id: {constraints['invoice_id']}. Vendor id: {constraints['vendor_id']}."
    return finance.run(client, task=task, session_id=session_id, token=token, conversation_factory=conversation_factory, log=log)
