// Client state (Zustand): the run being watched and the live event log. Server data lives in TanStack Query.
//
// Events arrive in bursts (the scripted agent finishes in well under a second; SSE polls every 0.3s), so the
// dashboard does not draw them on arrival. `events` holds everything received; `shown` holds the watched run's
// events that the playback pacer (hooks/usePlayback.ts) has revealed so far, one step at a time. Every view of
// the run reads `shown`, so the graph, verdict, feed, toasts and ledger stay in step with each other.
import { create } from "zustand";
import type { StreamStatus } from "./api";
import type { AgentMode, GateEvent, RunScenarioStarted } from "./types";

export interface RunInfo extends RunScenarioStarted {
  startedAt: number;
}

export interface Starting {
  scenario: string;
  agent: AgentMode;
  at: number;
}

interface LiveState {
  run: RunInfo | null;
  starting: Starting | null; // Run clicked, the gate is still launching the agent (no session yet)
  events: GateEvent[]; // every event received, oldest first, de-duplicated by seq
  shown: GateEvent[]; // the watched run's events revealed so far, oldest first
  stream: StreamStatus;
  ticks: { id: string | null; n: number }; // how many of the latest decision's checks are shown (hooks/useVerdict.ts)
  beginStart: (scenario: string, agent: AgentMode) => void;
  cancelStart: () => void;
  startRun: (r: RunScenarioStarted) => void;
  addEvents: (es: GateEvent[]) => void;
  reveal: (e: GateEvent) => void;
  setStream: (s: StreamStatus) => void;
  setTicks: (t: { id: string | null; n: number }) => void;
  clear: () => void;
}

function merge(existing: GateEvent[], incoming: GateEvent[]): GateEvent[] {
  const seen = new Set(existing.map((e) => e.seq));
  const fresh = incoming.filter((e) => !seen.has(e.seq));
  return fresh.length ? [...existing, ...fresh].sort((a, b) => a.seq - b.seq).slice(-500) : existing;
}

export const useLive = create<LiveState>((set) => ({
  run: null,
  starting: null,
  events: [],
  shown: [],
  stream: "connecting",
  ticks: { id: null, n: 0 },
  beginStart: (scenario, agent) => set({ starting: { scenario, agent, at: Date.now() }, run: null, shown: [] }),
  cancelStart: () => set({ starting: null }),
  startRun: (r) => set((s) => ({ run: { ...r, startedAt: s.starting?.at ?? Date.now() }, starting: null, shown: [] })),
  addEvents: (es) => set((s) => ({ events: merge(s.events, es) })),
  reveal: (e) => set((s) => (s.shown.some((x) => x.seq === e.seq) ? s : { shown: merge(s.shown, [e]) })),
  setStream: (stream) => set({ stream }),
  setTicks: (ticks) => set({ ticks }),
  clear: () => set({ run: null, starting: null, events: [], shown: [], ticks: { id: null, n: 0 } }),
}));

/** Events of the watched run, as revealed so far (stable reference between reveals). */
export function useRunEvents(): GateEvent[] {
  return useLive((s) => s.shown);
}

/** Events of the watched run that have arrived but are not revealed yet. */
export function pendingEvents(s: Pick<LiveState, "run" | "events" | "shown">): GateEvent[] {
  if (!s.run) return [];
  const shown = new Set(s.shown.map((e) => e.seq));
  return s.events.filter((e) => e.session_id === s.run!.session_id && !shown.has(e.seq));
}

export interface LatestDecision {
  decisionId: string;
  outcome: string;
  approval?: string;
}

/** How the watched run's process ended, once it has (null while it is still running). */
export function runFinished(events: GateEvent[]): { ok: boolean; detail: string | null } | null {
  const e = [...events].reverse().find((x) => x.type === "run_finished");
  return e ?{ ok: Boolean(e.data.ok), detail: (e.data.detail as string | null) ?? null } : null;
}

/** The latest decision of the watched run (the approval flow re-emits a decision for the same id). */
export function latestDecision(events: GateEvent[]): LatestDecision | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e?.type === "decision") {
      return { decisionId: String(e.data.decision_id), outcome: String(e.data.outcome), approval: e.data.approval as string | undefined };
    }
  }
  return null;
}

export type Stage = "mandate" | "gather" | "propose" | "check" | "verdict" | "money";
export type StageState = "todo" | "active" | "done" | "bad" | "warn";

export interface RunPhase {
  active: boolean; // something is still happening (starting, agent working, waiting for the human, paying)
  finished: boolean;
  stages: Record<Stage, StageState>;
  toolCalls: number;
  lastTool: string | null;
  proposal: { payee: string; amount: number } | null;
  decision: LatestDecision | null;
  payment: { status: string; payee: string; amount: number; error?: string } | null;
  ended: { ok: boolean; detail: string | null } | null; // the agent's process exited (run_finished)
}

/** Where the watched run is, derived from revealed events only. */
export function runPhase(starting: Starting | null, run: RunInfo | null, shown: GateEvent[]): RunPhase {
  let toolCalls = 0;
  let lastTool: string | null = null;
  let proposal: RunPhase["proposal"] = null;
  let payment: RunPhase["payment"] = null;
  for (const e of shown) {
    const d = e.data;
    if (e.type === "tool_call" && d.status === "ok") {
      toolCalls++;
      const args = Object.values((d.args ?? {}) as Record<string, unknown>).map(String).join(" ");
      lastTool = `${String(d.tool)}${args ? ` ${args}` : ""}`;
    } else if (e.type === "proposal") {
      proposal = { payee: String(d.payee_account), amount: Number(d.amount_paise) };
    } else if (e.type === "payment") {
      payment = { status: String(d.status), payee: String(d.payee_account), amount: Number(d.amount_paise), error: d.error as string | undefined };
    }
  }
  const decision = latestDecision(shown);
  const stages: Record<Stage, StageState> = { mandate: "todo", gather: "todo", propose: "todo", check: "todo", verdict: "todo", money: "todo" };
  if (starting) stages.mandate = "active";
  if (run) {
    stages.mandate = "done";
    stages.gather = proposal ? "done" : "active";
  }
  if (proposal) {
    stages.propose = "done";
    stages.check = decision ? "done" : "active";
  }
  let finished = false;
  if (decision) {
    const waiting = decision.outcome === "STEP_UP" && decision.approval === "pending";
    stages.verdict = decision.outcome === "BLOCK" ? "bad" : decision.outcome === "STEP_UP" ? "warn" : "done";
    if (decision.outcome === "BLOCK") {
      stages.money = "done"; // no pass, nothing moves: that is the success case for a scam
      finished = true;
    } else if (waiting) {
      stages.money = "warn";
    } else {
      stages.money = payment ? (payment.status === "paid" ? "done" : "bad") : "active";
      finished = !!payment;
    }
  }
  // The agent's process exited before the run reached its end (no proposal, a crash, an approval that timed out):
  // stop every spinner and mark the stage it stopped at.
  const ended = runFinished(shown);
  if (ended && !finished) {
    finished = true;
    for (const k of Object.keys(stages) as Stage[]) {
      if (stages[k] === "active") stages[k] = ended.ok ? "warn" : "bad";
    }
  }
  return {
    active: !!starting || (!!run && !finished),
    finished,
    stages,
    toolCalls,
    lastTool,
    proposal,
    decision,
    payment,
    ended,
  };
}
