// Provenance graph data for React Flow. Same node ids and column layout as the backend tracer
// (src:<ref> | tc:<tool_call_id> | proposal | decision; x = column × 280), so the live graph built
// from events turns into the final trace without nodes jumping.
import { type Edge, MarkerType, type Node } from "@xyflow/react";
import type { GateEvent, TraceGraph, TraceStatus } from "../types";
import { clock, inr } from "./utils";

export type NodeKind = "source" | "tool_call" | "proposal" | "decision";

interface NodeFields {
  label: string;
  status: TraceStatus;
  trust?: string | null;
  detail?: string | null;
}

// React Flow requires node data to be an indexable record.
export type MgNodeData = NodeFields & { kind: NodeKind } & Record<string, unknown>;

export type MgNode = Node<MgNodeData, "mg">;
export interface Graph {
  nodes: MgNode[];
  edges: Edge[];
}

const COL_W = 280;
const ROW_H = 112;
// Hex, not CSS vars: SVG marker attributes don't resolve var().
const EDGE_COLOR: Record<TraceStatus, string> = { good: "#3fd294", bad: "#ff6d64", warn: "#f4b64e", neutral: "#6b7798" };
const DECISION_LABEL: Record<string, string> = { BLOCK: "BLOCKED", ALLOW: "ALLOWED", STEP_UP: "ASK YOU FIRST" };

/** Short name on the first line, specifics on the second, so nothing truncates at demo zoom. */
export function sourceInfo(ref: string): { label: string; detail: string | null } {
  const [kind, rest = ""] = ref.split(/:(.*)/s);
  if (kind === "email") return { label: `Email #${rest}`, detail: null };
  if (kind === "vendor") return { label: "Vendor registry", detail: rest };
  if (kind === "invoice") {
    return rest.endsWith("#notes")
      ? { label: "Invoice notes", detail: `${rest.replace("#notes", "")} · free text` }
      : { label: "Invoice DB", detail: rest };
  }
  if (kind === "web") return { label: "Web page", detail: rest };
  return { label: ref, detail: null };
}

function toolLabel(tool: string, args: Record<string, unknown>): string {
  if (tool === "read_email") return `read_email #${String(args.email_id)}`;
  const extra = Object.values(args).map(String).join(" ");
  return `${tool}${extra ? ` ${extra}` : ""}`;
}

/** Column headings as nodes, so they stay aligned with their column at any zoom. */
function headings(): MgNode[] {
  return (["Sources", "Agent's tool calls", "Proposal", "Decision"] as const).map((text, col) => ({
    id: `head:${col}`, type: "head", position: { x: col * COL_W, y: -70 }, data: { kind: "source", label: text, status: "neutral" },
    draggable: false, selectable: false,
  })) as unknown as MgNode[];
}

function edge(id: string, source: string, target: string, status: TraceStatus, field?: string | null): Edge {
  const color = EDGE_COLOR[status];
  return {
    id, source, target,
    animated: status === "bad",
    label: field ? (field === "payee_account" ? "payee" : "amount") : undefined,
    labelBgPadding: [6, 3],
    labelBgBorderRadius: 6,
    style: { stroke: color, strokeWidth: status === "bad" ? 3 : status === "good" ? 2.2 : 1.4, opacity: status === "neutral" ? 0.55 : 1 },
    markerEnd: { type: MarkerType.ArrowClosed, color, width: 16, height: 16 },
  };
}

function node(id: string, kind: NodeKind, column: number, row: number, data: NodeFields): MgNode {
  return { id, type: "mg", position: { x: column * COL_W, y: row * ROW_H }, data: { kind, ...data }, draggable: false };
}

const COLUMN: Record<NodeKind, number> = { source: 0, tool_call: 1, proposal: 2, decision: 3 };

/** The final picture: the backend's trace, with friendlier proposal/decision labels. */
export function graphFromTrace(t: TraceGraph): Graph {
  const payee = t.fields.find((f) => f.field === "payee_account")?.value;
  const amount = t.fields.find((f) => f.field === "amount_paise")?.value;
  const nodes = t.nodes.map((n) => {
    let label = n.data.label;
    let detail = n.data.detail ?? null;
    if (n.type === "proposal" && amount !== undefined) {
      label = `Pay ${inr(Number(amount))}`;
      detail = `to ${payee ?? "?"}`;
    }
    if (n.type === "decision") label = DECISION_LABEL[n.data.label] ?? n.data.label;
    if (n.type === "source") {
      const info = sourceInfo(n.data.ref ?? n.data.label);
      label = info.label;
      detail = detail ?? info.detail; // emails keep "from <sender>"
    }
    if (n.type === "tool_call") {
      label = label.replace(/^[\w-]+: /, ""); // "finance: read_email #1842" → "read_email #1842"
      detail = `${(n.data.ref ?? "").split(":")[0]} · ${detail ? clock(detail) : ""}`;
    }
    return node(n.id, n.type, COLUMN[n.type], n.position.y / 120, { label, status: n.data.status, trust: n.data.trust, detail });
  });
  return { nodes: [...headings(), ...nodes], edges: t.edges.map((e) => edge(e.id, e.source, e.target, e.data.status, e.data.field)) };
}

/** The picture while the agent is still working, from live events only. */
export function graphFromEvents(events: GateEvent[]): Graph {
  const calls: { id: string; label: string; detail: string }[] = [];
  const sources: { ref: string; trust: string }[] = [];
  const links = new Set<string>();
  let proposal: { payee: string; amount: number } | null = null;
  let outcome: string | null = null;

  for (const e of events) {
    const d = e.data;
    if (e.type === "tool_call" && d.status === "ok") {
      calls.push({
        id: String(d.tool_call_id),
        label: toolLabel(String(d.tool), (d.args ?? {}) as Record<string, unknown>),
        detail: `${String(d.agent_id)} · ${clock(e.ts)}`,
      });
    } else if (e.type === "value_recorded") {
      const ref = String(d.source_ref);
      if (!sources.some((s) => s.ref === ref)) sources.push({ ref, trust: String(d.trust) });
      if (d.tool_call_id) links.add(`${ref}|${String(d.tool_call_id)}`);
    } else if (e.type === "proposal") {
      proposal = { payee: String(d.payee_account), amount: Number(d.amount_paise) };
    } else if (e.type === "decision") {
      outcome = String(d.outcome);
    }
  }

  const nodes: MgNode[] = [
    ...sources.map((s, i) =>
      node(`src:${s.ref}`, "source", 0, i, { ...sourceInfo(s.ref), status: s.trust === "trusted" ? "good" : "neutral", trust: s.trust })),
    ...calls.map((c, i) => node(`tc:${c.id}`, "tool_call", 1, i, { label: c.label, status: "neutral", detail: c.detail })),
  ];
  if (nodes.length) nodes.unshift(...headings());
  const edges: Edge[] = [...links].flatMap((l) => {
    const [ref, call] = l.split("|");
    return calls.some((c) => c.id === call) ? [edge(`src:${ref}->tc:${call}`, `src:${ref}`, `tc:${call}`, "neutral")] : [];
  });
  const mid = Math.max(sources.length, calls.length, 1) / 2 - 0.5;
  if (proposal) {
    nodes.push(node("proposal", "proposal", 2, mid, { label: `Pay ${inr(proposal.amount)}`, status: "neutral", detail: `to ${proposal.payee}` }));
  }
  if (outcome) {
    nodes.push(node("decision", "decision", 3, mid, { label: DECISION_LABEL[outcome] ?? outcome, status: "neutral", detail: "checking the trace…" }));
    edges.push(edge("proposal->decision", "proposal", "decision", "neutral"));
  }
  return { nodes, edges };
}
