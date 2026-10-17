import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { toast } from "sonner";
import { api, openEventStream } from "../api";
import { useLive } from "../store";
import type { GateEvent } from "../types";
import { inr } from "../lib/utils";

/** Toasts and data refreshes for an event, fired when it is shown (so they land in step with the visuals). */
export function announce(e: GateEvent, queryClient: QueryClient, mine: boolean, verdictDelayMs = 0): void {
  const d = e.data;
  if (e.type === "decision") {
    void queryClient.invalidateQueries({ queryKey: ["approvals"] });
    if (mine && d.via !== "approval") {
      window.setTimeout(() => { // with the stamp, not ahead of the checklist
        if (d.outcome === "BLOCK") toast.error("Payment blocked", { description: `Failed: ${(d.failed as string[]).join(", ")}` });
        else if (d.outcome === "STEP_UP") toast.warning("Over your limit: your approval is needed");
        else toast.success("Payment allowed");
      }, verdictDelayMs);
    }
  }
  if (e.type === "payment") {
    void queryClient.invalidateQueries({ queryKey: ["ledger"] });
    if (d.status === "paid") toast.success(`Paid ${inr(d.amount_paise as number)} to ${String(d.payee_account)}`);
    else toast.error(`Payment refused: ${String(d.error)}`);
  }
  if (e.type === "suspicious_input") {
    toast.warning("Suspicious input rejected", { description: `Fields: ${(d.fields as string[]).join(", ")}` });
  }
  if (e.type === "run_finished" && mine && !useLive.getState().shown.some((x) => x.type === "decision")) {
    const why = (d.detail as string | null) ?? "it ended without proposing a payment";
    if (d.ok) toast.info("The agent finished without proposing a payment", { description: why });
    else toast.error("The agent run failed", { description: why });
  }
  if (e.type === "escalation_attempt" && mine) {
    toast.warning("Escalation attempt logged", { description: (d.caveats as string[]).join("; ") });
  }
}

/** One SSE connection for the whole app. Events are stored, not drawn: the playback pacer reveals the
 *  watched run's events. Decision data is fetched as soon as it exists, so it is ready when revealed. */
export function useEventStream(): void {
  const queryClient = useQueryClient();
  const addEvents = useLive((s) => s.addEvents);
  const setStream = useLive((s) => s.setStream);

  useEffect(() => {
    const onEvent = (e: GateEvent) => {
      addEvents([e]);
      if (e.type === "decision") {
        const id = String(e.data.decision_id);
        void queryClient.prefetchQuery({ queryKey: ["decision", id], queryFn: () => api.decision(id), staleTime: 0 });
        void queryClient.prefetchQuery({ queryKey: ["trace", id], queryFn: () => api.trace(id), staleTime: 0 });
      }
      // Events of the watched run (or of a run being started) are announced when the pacer shows them.
      const { run, starting } = useLive.getState();
      const watched = (run && e.session_id === run.session_id) || (starting && !run);
      if (!watched) announce(e, queryClient, false);
    };
    return openEventStream(onEvent, setStream);
  }, [addEvents, setStream, queryClient]);
}
