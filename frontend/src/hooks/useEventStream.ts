import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { toast } from "sonner";
import { openEventStream } from "../api";
import { useLive } from "../store";
import type { GateEvent } from "../types";
import { inr } from "../lib/utils";

/** One SSE connection for the whole app: feeds the store, refreshes server data, raises toasts. */
export function useEventStream(): void {
  const queryClient = useQueryClient();
  const addEvent = useLive((s) => s.addEvent);
  const setStream = useLive((s) => s.setStream);

  useEffect(() => {
    const onEvent = (e: GateEvent) => {
      addEvent(e);
      const watched = useLive.getState().run?.session_id;
      const mine = watched !== undefined && e.session_id === watched;
      const d = e.data;
      if (e.type === "decision") {
        void queryClient.invalidateQueries({ queryKey: ["decision", d.decision_id] });
        void queryClient.invalidateQueries({ queryKey: ["trace", d.decision_id] });
        void queryClient.invalidateQueries({ queryKey: ["approvals"] });
        if (mine && d.via !== "approval") {
          if (d.outcome === "BLOCK") toast.error("Payment blocked", { description: `Failed: ${(d.failed as string[]).join(", ")}` });
          else if (d.outcome === "STEP_UP") toast.warning("Over your limit: your approval is needed");
          else toast.success("Payment allowed");
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
      if (e.type === "run_finished" && mine && !useLive.getState().events.some((x) => x.session_id === watched && x.type === "decision")) {
        const why = (d.detail as string | null) ?? "it ended without proposing a payment";
        if (d.ok) toast.info("The agent finished without proposing a payment", { description: why });
        else toast.error("The agent run failed", { description: why });
      }
      if (e.type === "escalation_attempt" && mine) {
        toast.warning("Escalation attempt logged", { description: (d.caveats as string[]).join("; ") });
      }
    };
    return openEventStream(onEvent, setStream);
  }, [addEvent, setStream, queryClient]);
}
