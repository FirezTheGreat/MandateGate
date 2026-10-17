"""Run one scenario end to end:

    python -m agents.run_scenario --scenario hero_attack --mode gated --agent llm

It plays the human/dashboard side (gate mode, mandate, session, step-up approval), runs the
planner → finance agent, pays with the one-time pass if the gate allowed it, and prints a summary.

--on-step-up: wait (default; poll until someone approves in the dashboard), approve, or deny.
Exit code: 0 when the run completed (whatever the decision), 1 on an infrastructure/agent error.
"""

import argparse
import json
import os
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agents import planner
from agents.gate_client import GateClient, GateError
from agents.llm import Conversation, LLMError, make_conversation

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "scenarios"
SCENARIO_NAME = re.compile(r"^[a-z0-9_]{1,64}$")
PRINCIPAL = "abhishek"


def rupees(paise: int | None) -> str:
    return "-" if paise is None else f"Rs. {paise / 100:,.2f}"


def load_scenario(name: str) -> dict[str, Any]:
    if not SCENARIO_NAME.match(name):
        raise ValueError(f"invalid scenario name {name!r}")
    path = SCENARIOS_DIR / f"{name}.json"
    if not path.is_file():
        raise ValueError(f"no scenario {name!r} in {SCENARIOS_DIR}")
    return json.loads(path.read_text(encoding="utf-8"))


def _await_human(client: GateClient, decision_id: str, timeout_s: float, log: Callable[[str], None]) -> dict[str, Any]:
    log(f"[human] waiting up to {int(timeout_s)}s for approval of {decision_id} (dashboard, or POST /approvals/{decision_id})")
    deadline = time.monotonic() + timeout_s
    decision = client.get_decision(decision_id)
    while decision["outcome"] == "STEP_UP" and time.monotonic() < deadline:
        time.sleep(1)
        decision = client.get_decision(decision_id)
    return decision


def run(
    scenario: str, mode: str, agent: str, *, client: GateClient, on_step_up: str = "wait", approval_timeout_s: float = 120,
    conversation_factory: Callable[..., Conversation] = make_conversation, log: Callable[[str], None] = print,
) -> dict[str, Any]:
    sc = load_scenario(scenario)
    result: dict[str, Any] = {
        "scenario": scenario, "mode": mode, "agent": agent, "expected": sc["expected"][mode], "error": None,
        "session_id": None, "decision_id": None, "outcome": None, "final_outcome": None, "failed_checks": [],
        "payee": None, "amount_paise": None, "payee_found": None, "paid": False, "paid_to": None,
        "paid_amount_paise": None, "attacker_paid": False, "agent_stopped": None, "agent_steps": 0,
    }

    client.set_mode(mode)
    created = client.create_mandate(PRINCIPAL, sc["mandate"])
    mandate, root_token = created["mandate"], created["token"]
    session = client.create_session(mandate["mandate_id"], scenario)
    result["session_id"] = session["session_id"]
    log(f"[human] {PRINCIPAL} approved: {sc['instruction']}  (mandate {mandate['mandate_id']}, mode {mode})")

    try:
        agent_run = planner.run(
            client, instruction=sc["instruction"], root_token=root_token, constraints=sc["mandate"],
            session_id=session["session_id"], agent=agent, conversation_factory=conversation_factory, log=log,  # type: ignore[arg-type]
        )
    except LLMError as e:
        result["error"] = f"agent could not run: {e}"
        return result
    result["agent_stopped"], result["agent_steps"] = agent_run.stopped, agent_run.steps

    decision = agent_run.decision
    if decision is None:
        result["error"] = f"agent did not propose a payment ({agent_run.stopped}) {agent_run.note}".strip()
        return result

    result["decision_id"], result["outcome"] = decision["decision_id"], decision["outcome"]
    result["failed_checks"] = [c["check"] for c in decision["checks"] if c["status"] == "fail"]
    result["payee"], result["amount_paise"] = decision["proposal"]["payee_account"], decision["proposal"]["amount_paise"]
    result["payee_found"] = next((c.get("found") for c in decision["checks"] if c["check"] == "payee_provenance"), None)

    if decision["outcome"] == "STEP_UP":
        if on_step_up == "wait":
            decision = _await_human(client, decision["decision_id"], approval_timeout_s, log)
        else:
            decision = client.approve(decision["decision_id"], on_step_up == "approve")
            log(f"[human] {'approved' if on_step_up == 'approve' else 'denied'} the step-up")
    result["final_outcome"] = decision["outcome"]

    if decision["outcome"] == "ALLOW" and decision.get("one_pass"):
        try:
            receipt = client.pay(decision["one_pass"])
            result.update(paid=True, paid_to=receipt["payee_account"], paid_amount_paise=receipt["amount_paise"])
            result["attacker_paid"] = receipt["payee_account"] == sc.get("attacker_payee")
        except GateError as e:
            result["error"] = f"payment service refused the pass: {e.error} ({e.detail})"
    return result


def summary(r: dict[str, Any]) -> list[str]:
    lines = [f"=== {r['scenario']} | {r['mode']} | agent={r['agent']} ==="]
    if r["outcome"]:
        lines.append(f"proposal   pay {rupees(r['amount_paise'])} to {r['payee']}")
        verdict = r["outcome"] if r["final_outcome"] in (None, r["outcome"]) else f"{r['outcome']} -> {r['final_outcome']}"
        if r["outcome"] == "STEP_UP":
            reason = "  (over the approved limit: asked the human)"
        else:
            reason = f"  (failed: {', '.join(r['failed_checks'])})" if r["failed_checks"] else ""
        lines.append(f"decision   {verdict}{reason}")
        if r["payee_found"] is not None:
            lines.append(f"payee seen {', '.join(r['payee_found']) or 'nowhere'}")
    if r["paid"]:
        lines.append(f"paid       {rupees(r['paid_amount_paise'])} to {r['paid_to']}" + ("   <-- ATTACKER PAID" if r["attacker_paid"] else ""))
    else:
        lines.append("paid       nothing")
    if r["error"]:
        lines.append(f"error      {r['error']}")
    met = "no decision reached" if r["outcome"] is None else "yes" if r["outcome"] == r["expected"] else "NO"
    lines.append(f"expected   {r['expected']}: {met}")
    return lines


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run a MandateGate scenario end to end.")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--mode", default="gated", choices=["gated", "baseline"])
    parser.add_argument("--agent", default=os.environ.get("AGENT_MODE", "llm"), choices=["llm", "scripted"])
    parser.add_argument("--on-step-up", default="wait", choices=["wait", "approve", "deny"])
    parser.add_argument("--approval-timeout", type=float, default=120)
    args = parser.parse_args()

    client = GateClient.from_env()
    try:
        r = run(args.scenario, args.mode, args.agent, client=client, on_step_up=args.on_step_up, approval_timeout_s=args.approval_timeout)
    except (GateError, ValueError) as e:
        print(f"error: {e}")
        return 1
    finally:
        client.close()
    print("\n".join(summary(r)))
    return 1 if r["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
