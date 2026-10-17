import { useAutoAnimate } from "@formkit/auto-animate/react";
import { Loader2 } from "lucide-react";
import { runPhase, useLive, useRunEvents } from "../store";
import type { GateEvent } from "../types";
import { clock, inr } from "../lib/utils";
import { Badge, Card, CardHeader, type Tone } from "./ui/card";

function describe(e: GateEvent): { kind: string; tone: Tone; title: string; text: string } {
  const d = e.data as Record<string, unknown>;
  switch (e.type) {
    case "tool_call":
      return { kind: "Tool call", tone: d.status === "ok" ? "neutral" : "bad", title: String(d.tool), text: d.status === "ok" ? `${String(d.agent_id)} · ${Object.values((d.args ?? {}) as object).join(" ")}` : `${String(d.status)}: ${String(d.error)}` };
    case "value_recorded":
      return { kind: "Value recorded", tone: d.trust === "trusted" ? "ok" : "warn", title: String(d.raw), text: `from ${String(d.source_ref)} · ${String(d.trust)}` };
    case "proposal":
      return { kind: "Proposal", tone: "seal", title: `${inr(d.amount_paise as number)} → ${String(d.payee_account)}`, text: `for ${String(d.invoice_id)}` };
    case "decision":
      return { kind: "Decision", tone: d.outcome === "ALLOW" ? "ok" : d.outcome === "BLOCK" ? "bad" : "warn", title: String(d.outcome), text: (d.failed as string[] | undefined)?.length ? `failed: ${(d.failed as string[]).join(", ")}` : d.via === "approval" ? "after your decision" : "all checks passed" };
    case "payment":
      return { kind: "Payment", tone: d.status === "paid" ? "ok" : "bad", title: d.status === "paid" ? `Paid ${inr(d.amount_paise as number)}` : `Refused: ${String(d.error)}`, text: `to ${String(d.payee_account)}` };
    case "suspicious_input":
      return { kind: "Suspicious", tone: "warn", title: (d.fields as string[]).join(", "), text: `rejected at ${String(d.path)}` };
    case "escalation_attempt":
      return { kind: "Escalation", tone: "warn", title: "Wider permission refused", text: (d.caveats as string[]).join("; ") };
    case "run_finished":
      return { kind: "Run ended", tone: d.ok ? "neutral" : "bad", title: d.ok ? "Agent finished" : "Agent run failed", text: String(d.detail ?? "") };
  }
}

export function EventFeed() {
  const events = useRunEvents();
  const run = useLive((s) => s.run);
  const starting = useLive((s) => s.starting);
  const phase = runPhase(starting, run, events);
  const [listRef] = useAutoAnimate<HTMLOListElement>({ duration: 180 });
  const shown = [...events].reverse().slice(0, 60);
  return (
    <Card>
      <CardHeader title="Live event feed" aside={<span className="font-mono text-xs text-faint">{events.length ? `${events.length} events` : "/events/stream"}</span>} />
      <ol ref={listRef} className="max-h-75 overflow-y-auto">
        {phase.active && (
          <li key="waiting" className="flex items-center gap-2 border-b border-line/70 py-1.5 text-[13.5px] text-muted">
            <Loader2 className="size-3.5 animate-spin text-seal" aria-hidden />
            {starting ? "Launching the agent…" : phase.decision?.approval === "pending" ? "Waiting for your approval…" : "Listening for the next step…"}
          </li>
        )}
        {shown.map((e) => {
          const v = describe(e);
          return (
            <li key={e.seq} className="grid grid-cols-[64px_120px_minmax(0,1fr)] items-baseline gap-2 border-b border-line/70 py-1.5 text-[13.5px]">
              <span className="font-mono text-xs text-faint tabular">{clock(e.ts)}</span>
              <Badge tone={v.tone} className="justify-self-start">{v.kind}</Badge>
              <span className="min-w-0 truncate"><b className="font-semibold">{v.title}</b> <span className="text-muted">{v.text}</span></span>
            </li>
          );
        })}
        {shown.length === 0 && !phase.active && <li key="empty" className="py-6 text-center text-sm text-muted">Events stream in here as the agent works.</li>}
      </ol>
    </Card>
  );
}
