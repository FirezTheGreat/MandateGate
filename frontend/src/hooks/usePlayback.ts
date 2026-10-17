import { useQueryClient } from "@tanstack/react-query";
import { useReducedMotion } from "motion/react";
import { useEffect, useRef } from "react";
import { pendingEvents, useLive } from "../store";
import type { EventType, GateEvent } from "../types";
import { announce } from "./useEventStream";
import { CHECKS_SETTLE_MS } from "./useVerdict";

// Pause before each kind of step appears (ms), counted from the previous step. A scripted run reveals in ~6s,
// so the audience can follow it; a real AI run is slower than this anyway and shows each step as it lands.
const PACE: Record<EventType, number> = {
  tool_call: 550,
  value_recorded: 90,
  proposal: 750,
  decision: 900,
  payment: 800,
  escalation_attempt: 450,
  suspicious_input: 450,
  run_finished: 400,
};

function pace(e: GateEvent, prev: GateEvent | undefined, backlog: number): number {
  // The verdict lands before anything moves (a decision re-sent after your approval does not re-tick its checks).
  if (prev?.type === "decision" && prev.data.via !== "approval") return CHECKS_SETTLE_MS + 400;
  const base = PACE[e.type] ?? 300;
  return backlog > 40 ? base / 3 : backlog > 20 ? base / 2 : base;
}

/** Reveals the watched run's events one at a time. Instant with reduced motion. */
export function usePlayback(): void {
  const queryClient = useQueryClient();
  const reduced = useReducedMotion();
  const run = useLive((s) => s.run);
  const events = useLive((s) => s.events);
  const shown = useLive((s) => s.shown);
  const reveal = useLive((s) => s.reveal);
  const lastAt = useRef(0);

  useEffect(() => {
    const queue = pendingEvents({ run, events, shown });
    const next = queue[0];
    if (!next) return;
    const step = () => {
      lastAt.current = Date.now();
      if (reduced) queue.forEach(reveal);
      else reveal(next);
      for (const e of reduced ? queue : [next]) announce(e, queryClient, true, reduced ? 0 : CHECKS_SETTLE_MS);
    };
    if (reduced) {
      step();
      return;
    }
    const wait = shown.length === 0 ? 250 : Math.max(0, lastAt.current + pace(next, shown.at(-1), queue.length) - Date.now());
    const timer = window.setTimeout(step, wait);
    return () => window.clearTimeout(timer);
  }, [run, events, shown, reveal, reduced, queryClient]);
}
