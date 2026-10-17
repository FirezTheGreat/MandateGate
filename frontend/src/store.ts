// Client state (Zustand): the run being watched and the live event log. Server data lives in TanStack Query.
import { create } from "zustand";
import type { StreamStatus } from "./api";
import type { GateEvent, RunScenarioStarted } from "./types";

export interface RunInfo extends RunScenarioStarted {
  startedAt: number;
}

interface LiveState {
  run: RunInfo | null;
  events: GateEvent[]; // every event received, oldest first, de-duplicated by seq
  stream: StreamStatus;
  startRun: (r: RunScenarioStarted) => void;
  addEvent: (e: GateEvent) => void;
  addEvents: (es: GateEvent[]) => void;
  setStream: (s: StreamStatus) => void;
  clear: () => void;
}

function merge(existing: GateEvent[], incoming: GateEvent[]): GateEvent[] {
  const seen = new Set(existing.map((e) => e.seq));
  const fresh = incoming.filter((e) => !seen.has(e.seq));
  return fresh.length ? [...existing, ...fresh].sort((a, b) => a.seq - b.seq).slice(-500) : existing;
}

export const useLive = create<LiveState>((set) => ({
  run: null,
  events: [],
  stream: "connecting",
  startRun: (r) => set({ run: { ...r, startedAt: Date.now() } }),
  addEvent: (e) => set((s) => ({ events: merge(s.events, [e]) })),
  addEvents: (es) => set((s) => ({ events: merge(s.events, es) })),
  setStream: (stream) => set({ stream }),
  clear: () => set({ run: null, events: [] }),
}));

/** Events of the run being watched. */
export function useRunEvents(): GateEvent[] {
  const run = useLive((s) => s.run);
  const events = useLive((s) => s.events);
  return run ? events.filter((e) => e.session_id === run.session_id) : [];
}

/** The latest decision of the watched run (the approval flow re-emits a decision for the same id). */
export function latestDecision(events: GateEvent[]): { decisionId: string; outcome: string; approval?: string } | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e?.type === "decision") {
      return { decisionId: String(e.data.decision_id), outcome: String(e.data.outcome), approval: e.data.approval as string | undefined };
    }
  }
  return null;
}
