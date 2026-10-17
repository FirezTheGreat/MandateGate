"""Attack tracer: rebuild, for one decision, how every critical value reached the proposal.

    source (vendor registry / invoice DB / email / web) → tool call (agent: tool) → proposal → decision

Pure (no I/O): the route loads the decision, the session's tool calls and its value records.
Values are matched by normalized form (provenance.matches), so an agent that rewrote
"EVE-777" as "E V E 777" cannot hide where it came from. Field status uses the same rules
as the policy (registered_payee_records / amount_due_values), in both modes: in baseline the
gate did not check, but the trace still shows the truth.

Status colours: good (trusted path), bad (offending path), warn (waiting for the human), neutral.
"""

import json
from dataclasses import dataclass
from typing import Any, Literal

from app.models import Decision, Position, TraceEdge, TraceEdgeData, TraceField, TraceGraph, TraceNode, TraceNodeData, ValueRecord
from app.policy import amount_due_values, registered_payee_records
from app.provenance import describe, matches

COLUMN_X = {"source": 0, "tool_call": 1, "proposal": 2, "decision": 3}
COL_W, ROW_H = 280, 120
Status = Literal["good", "bad", "neutral", "warn"]


@dataclass(frozen=True)
class ToolCallRecord:
    tool_call_id: str
    agent_id: str
    tool: str
    args: dict[str, Any]
    ts: str


def source_label(ref: str) -> str:
    kind, _, rest = ref.partition(":")
    if kind == "email":
        return f"Email #{rest}"
    if kind == "vendor":
        return f"Vendor registry: {rest}"
    if kind == "invoice":
        inv, _, part = rest.partition("#")
        return f"Invoice notes: {inv}" if part == "notes" else f"Invoice DB: {inv}"
    if kind == "web":
        return f"Web page: {rest}"
    return ref


def tool_label(call: ToolCallRecord) -> str:
    if call.tool == "read_email":
        return f"{call.agent_id}: read_email #{call.args.get('email_id')}"
    extra = " ".join(str(v) for v in call.args.values())
    return f"{call.agent_id}: {call.tool}" + (f" {extra}" if extra else "")


def _pos(kind: str, row: float) -> Position:
    return Position(x=COLUMN_X[kind] * COL_W, y=row * ROW_H)


def build_trace(decision: Decision, calls: list[ToolCallRecord], records: list[ValueRecord]) -> TraceGraph:
    p = decision.proposal
    by_call: dict[str, list[ValueRecord]] = {}
    for r in records:
        by_call.setdefault(r.tool_call_id, []).append(r)
    calls = [c for c in calls if c.tool_call_id in by_call]

    # ---- critical fields: where did each value appear, and does it trace to its required trusted source?
    payee_seen = matches(records, p.payee_account)
    payee_good = any(r.raw == p.payee_account for r in registered_payee_records(payee_seen, p.payee_account, p.vendor_id))
    amount_seen = matches(records, str(p.amount_paise), contained=False)
    amount_good = p.amount_paise in amount_due_values(records, p.invoice_id)

    def satisfies(field: str, r: ValueRecord) -> bool:
        """Is this record the trusted source the policy requires for the field?"""
        if field == "payee_account":
            return bool(registered_payee_records([r], p.payee_account, p.vendor_id)) and r.raw == p.payee_account
        return p.amount_paise in amount_due_values([r], p.invoice_id)

    fields = [
        TraceField(field="payee_account", value=p.payee_account, status="good" if payee_good else "bad", sources=describe(payee_seen)),
        TraceField(field="amount_paise", value=str(p.amount_paise), status="good" if amount_good else "bad", sources=describe(amount_seen)),
    ]
    any_bad_field = not (payee_good and amount_good)

    # ---- tool call → proposal edges, one per (tool call, field)
    critical: dict[tuple[str, str], Status] = {}
    bad_refs: set[str] = set()
    for field, seen, good in (("payee_account", payee_seen, payee_good), ("amount_paise", amount_seen, amount_good)):
        for r in seen:
            key = (r.tool_call_id, field)
            status: Status = ("good" if satisfies(field, r) else "neutral") if good else "bad"
            if critical.get(key) not in ("good", "bad"):
                critical[key] = status
            if status == "bad":
                bad_refs.add(r.source_ref)

    # ---- outcome colours
    if decision.outcome == "BLOCK":
        decision_status: Status = "bad"
    elif decision.outcome == "STEP_UP":
        decision_status = "warn"
    else:
        decision_status = "bad" if any_bad_field else "good"
    proposal_status: Status = "bad" if any_bad_field or decision.outcome == "BLOCK" else ("warn" if decision.outcome == "STEP_UP" else "good")

    # ---- source nodes (ordered by first appearance)
    source_refs: list[str] = []
    for c in calls:
        for r in by_call[c.tool_call_id]:
            if r.source_ref not in source_refs:
                source_refs.append(r.source_ref)
    trust_of = {r.source_ref: r.trust for r in records}
    sender = {r.source_ref: r.raw for r in records if r.field_hint == "from" or r.field_hint.endswith("].from")}

    def source_status(ref: str) -> Status:
        if ref in bad_refs:
            return "bad"
        return "good" if trust_of[ref] == "trusted" else "neutral"

    nodes: list[TraceNode] = [
        TraceNode(
            id=f"src:{ref}", type="source", position=_pos("source", i),
            data=TraceNodeData(
                label=source_label(ref), status=source_status(ref), trust=trust_of[ref], ref=ref,  # type: ignore[arg-type]
                detail=f"from {sender[ref]}" if ref in sender else None,
            ),
        )
        for i, ref in enumerate(source_refs)
    ]

    # ---- tool call nodes and source → tool edges
    edges: list[TraceEdge] = []
    for i, c in enumerate(calls):
        outgoing = [s for (cid, _), s in critical.items() if cid == c.tool_call_id]
        trusted_read = any(r.trust == "trusted" for r in by_call[c.tool_call_id])
        status: Status = "bad" if "bad" in outgoing else ("good" if trusted_read else "neutral")
        nodes.append(TraceNode(
            id=f"tc:{c.tool_call_id}", type="tool_call", position=_pos("tool_call", i),
            data=TraceNodeData(label=tool_label(c), status=status, ref=f"{c.agent_id}:{c.tool}", detail=c.ts),
        ))
        for ref in dict.fromkeys(r.source_ref for r in by_call[c.tool_call_id]):
            src = source_status(ref)
            e_status: Status = "bad" if src == "bad" and status == "bad" else ("good" if trust_of[ref] == "trusted" else "neutral")
            edges.append(TraceEdge(id=f"src:{ref}->tc:{c.tool_call_id}", source=f"src:{ref}", target=f"tc:{c.tool_call_id}",
                                   data=TraceEdgeData(status=e_status)))

    # ---- proposal and decision
    mid = max(len(source_refs), len(calls), 1) / 2 - 0.5
    failed = [ch.check for ch in decision.checks if ch.status == "fail"]
    nodes.append(TraceNode(
        id="proposal", type="proposal", position=_pos("proposal", mid),
        data=TraceNodeData(label=f"Pay {p.amount_paise} paise to {p.payee_account}", status=proposal_status,
                           ref=f"{p.agent_id}:propose_payment", detail=f"{p.invoice_id} / {p.vendor_id}"),
    ))
    if decision.outcome == "ALLOW" and any_bad_field:
        decision_detail = "allowed in baseline mode: provenance not checked"
    elif failed:
        decision_detail = "failed: " + ", ".join(failed)
    else:
        decision_detail = "over the approved limit: waiting for the human" if decision.outcome == "STEP_UP" else "all checks passed"
    nodes.append(TraceNode(
        id="decision", type="decision", position=_pos("decision", mid),
        data=TraceNodeData(label=decision.outcome, status=decision_status, ref=decision.decision_id, detail=decision_detail),
    ))
    value_of = {"payee_account": p.payee_account, "amount_paise": str(p.amount_paise)}
    for (cid, field), status in critical.items():
        edges.append(TraceEdge(id=f"tc:{cid}->proposal#{field}", source=f"tc:{cid}", target="proposal",
                               data=TraceEdgeData(status=status, field=field, value=value_of[field])))
    edges.append(TraceEdge(id="proposal->decision", source="proposal", target="decision", data=TraceEdgeData(status=decision_status)))
    return TraceGraph(decision_id=decision.decision_id, nodes=nodes, edges=edges, fields=fields)


def tool_call_records(rows: list[dict[str, Any]]) -> list[ToolCallRecord]:
    return [ToolCallRecord(r["tool_call_id"], r["agent_id"], r["tool"], json.loads(r["args"]), r["ts"]) for r in rows]
