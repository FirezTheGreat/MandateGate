import { useQuery } from "@tanstack/react-query";
import { useReducedMotion } from "motion/react";
import { useEffect } from "react";
import { api } from "../api";
import { latestDecision, useLive, useRunEvents } from "../store";

export const CHECK_TICK_MS = 170;
/** From the decision appearing to the stamp landing: six check ticks plus the stamp's spring. */
export const CHECKS_SETTLE_MS = CHECK_TICK_MS * 6 + 300;

function useLatestDecision() {
  const latest = latestDecision(useRunEvents());
  const query = useQuery({ queryKey: ["decision", latest?.decisionId], queryFn: () => api.decision(latest!.decisionId), enabled: !!latest });
  return { latest, query };
}

/** The one clock that ticks the checklist in (mounted once, in <Conductor />). Keyed by decision id, so the
 *  decision re-sent after an approval doesn't replay the sequence. Instant with reduced motion. */
export function useVerdictClock(): void {
  const reduced = useReducedMotion();
  const { query } = useLatestDecision();
  const id = query.data?.decision_id ?? null;
  const total = query.data?.checks.length ?? 0;
  const ticks = useLive((s) => s.ticks);
  const setTicks = useLive((s) => s.setTicks);

  useEffect(() => {
    if (!id) return;
    if (ticks.id !== id || reduced) {
      if (ticks.id !== id || ticks.n < total) setTicks({ id, n: reduced ? total : 0 });
      return;
    }
    if (ticks.n >= total) return;
    const timer = window.setTimeout(() => setTicks({ id, n: ticks.n + 1 }), CHECK_TICK_MS);
    return () => window.clearTimeout(timer);
  }, [id, total, ticks, reduced, setTicks]);
}

/** The watched run's latest decision and how far its checklist has ticked in. Every view that shows the
 *  outcome (progress strip, graph, verdict, ledger, approval modal) waits for `ready`, so they land together. */
export function useVerdict() {
  const { latest, query } = useLatestDecision();
  const decision = query.data ?? null;
  const ticks = useLive((s) => s.ticks);
  const total = decision?.checks.length ?? 0;
  const ticked = decision && ticks.id === decision.decision_id ? Math.min(ticks.n, total) : 0;
  const ready = (!!decision && ticked >= total) || query.isError; // display only: never hide an outcome for good
  return { latest, decision, ticked, ready };
}
