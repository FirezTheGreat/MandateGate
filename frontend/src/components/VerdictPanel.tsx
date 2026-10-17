import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Loader2, MinusCircle, Ticket, XCircle } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { api } from "../api";
import { cn, inr } from "../lib/utils";
import { latestDecision, runFinished, useLive, useRunEvents } from "../store";
import type { CheckName, CheckResult, CheckStatus, Decision, TraceGraph } from "../types";
import { Button } from "./ui/button";
import { Card, CardHeader } from "./ui/card";

const CHECK_TEXT: Record<CheckName, string> = {
  mandate_valid: "Your approval is genuine",
  delegation_chain: "The agent has permission",
  invoice_matches_mandate: "Right invoice, right vendor",
  payee_provenance: "Payee came from a trusted source",
  amount_provenance: "Amount matches the real invoice",
  amount_within_limit: "Within your approved limit",
};

function CheckIcon({ check, outcome }: { check: CheckResult; outcome: string }) {
  const status: CheckStatus = check.status;
  if (status === "pass") return <CheckCircle2 className="size-5 text-ok" aria-label="passed" />;
  if (status === "skipped") return <MinusCircle className="size-5 text-faint" aria-label="skipped" />;
  if (check.check === "amount_within_limit" && outcome === "STEP_UP") return <AlertTriangle className="size-5 text-warn" aria-label="over limit" />;
  return <XCircle className="size-5 text-bad" aria-label="failed" />;
}

function Stamp({ decision, attackerPaid }: { decision: Decision | null; attackerPaid: boolean }) {
  const view = !decision
    ? { key: "idle", text: "AWAITING PROPOSAL", sub: "Checks run when the agent proposes a payment", cls: "border-dashed border-line text-muted rotate-0" }
    : decision.outcome === "BLOCK"
      ? { key: "block", text: "BLOCKED", sub: "No one-time pass issued · nothing paid", cls: "border-bad text-bad bg-bad/10 -rotate-2" }
      : decision.outcome === "STEP_UP"
        ? { key: "step", text: "ASK YOU FIRST", sub: "Over your approved limit", cls: "border-warn text-warn bg-warn/10 -rotate-2" }
        : attackerPaid
          ? { key: "bad-allow", text: "ALLOWED", sub: `${inr(decision.proposal.amount_paise)} sent to ${decision.proposal.payee_account}`, cls: "border-bad text-bad bg-bad/10 -rotate-2" }
          : { key: "allow", text: "ALLOWED", sub: `${inr(decision.proposal.amount_paise)} to ${decision.proposal.payee_account}`, cls: "border-ok text-ok bg-ok/10 -rotate-2" };
  return (
    <div className="flex justify-center py-3">
      <AnimatePresence mode="wait">
        <motion.div
          key={view.key + (decision?.decision_id ?? "")}
          role="status"
          initial={decision ? { scale: 1.8, opacity: 0 } : { opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ type: "spring", stiffness: 420, damping: 22 }}
          className={cn("flex flex-col items-center rounded-lg border-[3px] px-6 py-2.5 text-center outline-1 outline-offset-4", view.cls, decision && "outline outline-current")}
        >
          <span className={cn("font-display font-black leading-none tracking-[0.07em]", decision ? "text-[34px] [font-stretch:125%]" : "text-lg")}>{view.text}</span>
          <span className="mt-1 text-xs font-semibold">{view.sub}</span>
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

function callout(decision: Decision, trace: TraceGraph | undefined, scenario: string | undefined, agentIsAi: boolean): string | null {
  const payee = trace?.fields.find((f) => f.field === "payee_account");
  if (decision.outcome === "BLOCK" && payee?.status === "bad") {
    const where = payee.sources[0] ?? "a source the gate never saw";
    return `The agent never told MandateGate where ${decision.proposal.payee_account} came from. MandateGate watched it arrive in ${where} itself, because every tool call goes through it.`;
  }
  if (decision.outcome === "ALLOW" && payee?.status === "bad") {
    return "Every ordinary check passed and the attacker was paid. Access control confirms who is acting; it never asks where the account number came from.";
  }
  if (decision.outcome === "ALLOW" && scenario === "hero_attack" && agentIsAi) {
    return "The AI agent caught this scam itself and paid the real vendor. That's luck you can't build on; MandateGate's guarantee doesn't depend on it.";
  }
  if (decision.outcome === "ALLOW") return "Legit payments go through untouched: the pass works once, for exactly this amount and account, for 2 minutes.";
  if (decision.outcome === "STEP_UP") return "Everything checks out except the amount, so MandateGate doesn't guess. It asks you.";
  return null;
}

export function VerdictPanel({ onReview }: { onReview: () => void }) {
  const run = useLive((s) => s.run);
  const events = useRunEvents();
  const latest = latestDecision(events);
  const decision = useQuery({ queryKey: ["decision", latest?.decisionId], queryFn: () => api.decision(latest!.decisionId), enabled: !!latest });
  const trace = useQuery({ queryKey: ["trace", latest?.decisionId], queryFn: () => api.trace(latest!.decisionId), enabled: !!latest });
  const d = decision.data ?? null;
  const payeeField = trace.data?.fields.find((f) => f.field === "payee_account");
  const attackerPaid = d?.outcome === "ALLOW" && payeeField?.status === "bad";
  const finished = runFinished(events);
  const working = run && !latest && !finished;
  const stopped = run && !latest && finished;
  const toolCalls = events.filter((e) => e.type === "tool_call").length;
  const failed = d?.checks.find((c) => c.status === "fail" && c.required);
  const note = d ? callout(d, trace.data, run?.scenario, run?.agent === "llm") : null;

  return (
    <Card>
      <CardHeader title="Verdict" aside={d && <span className="font-mono text-xs text-faint">{d.decision_id}</span>} />
      <Stamp decision={d} attackerPaid={attackerPaid} />
      {working && (
        <p className="mb-2 flex items-center justify-center gap-2 text-sm text-muted">
          <Loader2 className="size-4 animate-spin" aria-hidden /> {run.agent_label} is working · {toolCalls} tool call{toolCalls === 1 ? "" : "s"}
        </p>
      )}
      {stopped && (
        <div role="status" className="mb-2 rounded-lg bg-warn/10 px-3 py-2.5 text-sm">
          <div className="font-semibold text-warn">
            {finished.ok ? `${run.agent_label} finished without proposing a payment` : `${run.agent_label} could not finish`}
          </div>
          {finished.detail && <div className="mt-0.5 text-muted">{finished.detail}</div>}
          <div className="mt-0.5 text-muted">Nothing was paid. No payment was proposed, so MandateGate had nothing to decide.</div>
        </div>
      )}
      <ol className="space-y-1">
        {(d?.checks ?? []).map((c, i) => (
          <motion.li
            key={c.check}
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.07 }}
            className={cn("flex gap-3 rounded-lg px-2.5 py-2", c.status === "fail" && (d?.outcome === "STEP_UP" ? "bg-warn/10" : "bg-bad/10"))}
          >
            <CheckIcon check={c} outcome={d?.outcome ?? ""} />
            <div className="min-w-0">
              <div className="text-[15px] font-semibold leading-tight">
                {CHECK_TEXT[c.check]} <span className="ml-1 font-mono text-[11px] font-normal text-faint">{c.check}</span>
              </div>
              {c.detail && <div className="text-[13px] leading-snug text-muted">{c.detail}</div>}
            </div>
          </motion.li>
        ))}
        {!d && !working && <li className="px-2 text-sm text-muted">Six checks run on every proposed payment.</li>}
      </ol>

      {failed && failed.required && d?.outcome === "BLOCK" && (
        <div className="mt-3 grid grid-cols-[1fr_auto_1fr] items-center gap-3 rounded-xl border border-line p-3">
          <div>
            <div className="text-[11px] font-bold uppercase tracking-widest text-muted">Required</div>
            <div className="font-semibold text-ok">{failed.required}</div>
          </div>
          <div className="font-display text-2xl font-black text-bad" aria-hidden>≠</div>
          <div>
            <div className="text-[11px] font-bold uppercase tracking-widest text-muted">Found</div>
            <div className="font-semibold text-bad">{failed.found?.length ? failed.found.join(", ") : "nowhere (unknown origin)"}</div>
          </div>
        </div>
      )}

      {d?.one_pass && (
        <div className={cn("mt-3 grid grid-cols-[1fr_auto] overflow-hidden rounded-xl border-[1.5px]", attackerPaid ? "border-bad" : "border-ok")}>
          <div className="min-w-0 p-3">
            <div className={cn("flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-widest", attackerPaid ? "text-bad" : "text-ok")}>
              <Ticket className="size-3.5" aria-hidden /> One-time pass · {d.one_pass.pass_id}
            </div>
            <div className="truncate font-mono text-[13px]">{inr(d.one_pass.amount_paise)} → {d.one_pass.payee_account} · {d.one_pass.invoice_id}</div>
          </div>
          <div className={cn("grid place-items-center border-l-[1.5px] border-dashed px-4 text-center font-mono text-xs", attackerPaid ? "border-bad bg-bad/10" : "border-ok bg-ok/10")}>
            <b className="text-base">2:00</b>single use
          </div>
        </div>
      )}

      {latest?.outcome === "STEP_UP" && latest.approval === "pending" && (
        <div className="mt-3 flex justify-center">
          <Button variant="primary" onClick={onReview}>Review the request</Button>
        </div>
      )}
      {note && <p className="mt-3 rounded-xl bg-panel-2 px-3 py-2.5 text-[14px] leading-relaxed">{note}</p>}
    </Card>
  );
}
