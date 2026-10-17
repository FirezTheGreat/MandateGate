import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Circle, Loader2, MinusCircle, Ticket, XCircle } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { api } from "../api";
import { useVerdict } from "../hooks/useVerdict";
import { cn, inr } from "../lib/utils";
import { runPhase, useLive, useRunEvents } from "../store";
import { CHECK_ORDER, type CheckName, type CheckResult, type CheckStatus, type Decision, type TraceGraph } from "../types";
import { Button } from "./ui/button";
import { Card, CardHeader, Skeleton } from "./ui/card";

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
  if (status === "pass") return <CheckCircle2 className="size-5 shrink-0 text-ok" aria-label="passed" />;
  if (status === "skipped") return <MinusCircle className="size-5 shrink-0 text-faint" aria-label="skipped" />;
  if (check.check === "amount_within_limit" && outcome === "STEP_UP") return <AlertTriangle className="size-5 shrink-0 text-warn" aria-label="over limit" />;
  return <XCircle className="size-5 shrink-0 text-bad" aria-label="failed" />;
}

type StampView = { key: string; text: string; sub: string; cls: string; final: boolean };

function stampView(decision: Decision | null, ready: boolean, attackerPaid: boolean, phase: ReturnType<typeof runPhase>): StampView {
  if (decision && ready) {
    if (decision.outcome === "BLOCK") return { key: "block", text: "BLOCKED", sub: "No one-time pass issued · nothing paid", cls: "border-bad text-bad bg-bad/5", final: true };
    if (decision.outcome === "STEP_UP") return { key: "step", text: "ASK YOU FIRST", sub: "Over your approved limit", cls: "border-warn text-warn bg-warn/5", final: true };
    const sub = `${inr(decision.proposal.amount_paise)}${attackerPaid ? " sent" : ""} to ${decision.proposal.payee_account}`;
    return { key: attackerPaid ? "bad-allow" : "allow", text: "ALLOWED", sub, cls: attackerPaid ? "border-bad text-bad bg-bad/5" : "border-ok text-ok bg-ok/5", final: true };
  }
  if (phase.proposal) return { key: "checking", text: "CHECKING", sub: "Six checks on the proposed payment", cls: "border-seal/50 text-seal", final: false };
  if (phase.ended && !decision) {
    return { key: "ended", text: "NO PROPOSAL", sub: "The agent stopped before asking to pay", cls: "border-warn/60 text-warn", final: false };
  }
  if (phase.active) {
    const n = phase.toolCalls;
    return { key: "working", text: "AGENT AT WORK", sub: n ? `${n} tool call${n === 1 ? "" : "s"} so far, all through the gate` : "Starting the agent…", cls: "border-line text-muted", final: false };
  }
  return { key: "idle", text: "AWAITING PROPOSAL", sub: "Checks run when the agent proposes a payment", cls: "border-dashed border-line text-faint", final: false };
}

function Stamp({ view, decisionId }: { view: StampView; decisionId: string | undefined }) {
  return (
    <div className="flex min-h-27 items-center justify-center py-3">
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={view.key + (view.final ? decisionId ?? "" : "")}
          role="status"
          initial={view.final ? { scale: 1.6, opacity: 0, rotate: -2 } : { opacity: 0, y: 4 }}
          animate={view.final ? { scale: 1, opacity: 1, rotate: -2 } : { opacity: 1, y: 0 }}
          exit={{ opacity: 0, transition: { duration: 0.12 } }}
          transition={view.final ? { type: "spring", stiffness: 380, damping: 24 } : { duration: 0.2 }}
          className={cn("flex flex-col items-center rounded-lg px-6 py-2.5 text-center", view.final ? "border-4 border-double" : "border-2", view.cls)}
        >
          <span className={cn("flex items-center gap-2 font-display font-black leading-none", view.final ? "text-[38px] tracking-[0.06em]" : "text-[19px] tracking-[0.08em]")}>
            {!view.final && view.key !== "idle" && <Loader2 className="size-4 animate-spin" aria-hidden />}
            {view.text}
          </span>
          <span className="mt-1.5 text-[12.5px] font-medium">{view.sub}</span>
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
  const starting = useLive((s) => s.starting);
  const events = useRunEvents();
  const phase = runPhase(starting, run, events);
  // The six checks tick in one by one, then the stamp lands. Keyed by decision id, so the
  // re-emitted decision after an approval doesn't replay the whole sequence.
  const { latest, decision: d, ticked, ready } = useVerdict();
  const trace = useQuery({ queryKey: ["trace", latest?.decisionId], queryFn: () => api.trace(latest!.decisionId), enabled: !!latest });
  const checking = !!phase.proposal && !ready;

  const payeeField = trace.data?.fields.find((f) => f.field === "payee_account");
  const attackerPaid = d?.outcome === "ALLOW" && payeeField?.status === "bad";
  const stopped = run && !latest ? phase.ended : null; // the agent exited without proposing a payment
  const failed = d?.checks.find((c) => c.status === "fail" && c.required);
  const note = d && ready ? callout(d, trace.data, run?.scenario, run?.agent === "llm") : null;
  const view = stampView(d, ready, attackerPaid, phase);

  return (
    <Card>
      <CardHeader title="Verdict" aside={d && <span className="font-mono text-xs text-faint">{d.decision_id}</span>} />
      <Stamp view={view} decisionId={d?.decision_id} />
      {stopped && run && (
        <div className="mb-3 rounded-xl border border-warn/30 bg-warn/5 px-3.5 py-2.5 text-sm">
          <div className="font-semibold text-warn">
            {stopped.ok ? `${run.agent_label} finished without proposing a payment` : `${run.agent_label} could not finish`}
          </div>
          {stopped.detail && <div className="mt-0.5 text-muted">{stopped.detail}</div>}
          <div className="mt-0.5 text-muted">Nothing was paid. No payment was proposed, so MandateGate had nothing to decide.</div>
        </div>
      )}

      <ol className="space-y-0.5" aria-busy={checking}>
        {(d?.checks ?? (phase.proposal ? CHECK_ORDER.map((check) => ({ check }) as CheckResult) : [])).map((c, i) => {
          const shown = !!d && i < ticked;
          const failing = shown && c.status === "fail";
          return (
            <li
              key={c.check}
              className={cn("flex gap-3 rounded-lg px-2.5 py-1.5 transition-colors duration-300", failing && (d?.outcome === "STEP_UP" ? "bg-warn/8" : "bg-bad/8"))}
            >
              {shown ? (
                <motion.span initial={{ scale: 0.4, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ type: "spring", stiffness: 500, damping: 26 }}>
                  <CheckIcon check={c} outcome={d?.outcome ?? ""} />
                </motion.span>
              ) : i === ticked ? (
                <Loader2 className="size-5 shrink-0 animate-spin text-seal" aria-label="checking" />
              ) : (
                <Circle className="size-5 shrink-0 text-line" aria-hidden />
              )}
              <div className="min-w-0 flex-1">
                <div className={cn("text-[15px] font-semibold leading-tight transition-colors", !shown && "text-muted")}>
                  {CHECK_TEXT[c.check]} <span className="ml-1 font-mono text-[11px] font-normal text-faint">{c.check}</span>
                </div>
                {shown ? (
                  c.detail && <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-[13px] leading-snug text-muted">{c.detail}</motion.div>
                ) : (
                  <Skeleton className="mt-1 h-3 w-3/5" />
                )}
              </div>
            </li>
          );
        })}
        {!phase.proposal && (
          <li className="px-2.5 text-[14px] text-muted">
            {phase.active ? "The gate checks the payment the moment the agent proposes one." : "Six checks run on every proposed payment."}
          </li>
        )}
      </ol>

      <AnimatePresence>
        {ready && failed?.required && d?.outcome === "BLOCK" && (
          <motion.div
            key="req"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            className="mt-3 grid grid-cols-[1fr_auto_1fr] items-center gap-3 rounded-xl border border-line bg-panel-2/60 p-3"
          >
            <div>
              <div className="text-[12px] font-medium text-muted">Required</div>
              <div className="font-semibold text-ok">{failed.required}</div>
            </div>
            <div className="font-display text-3xl font-black text-bad" aria-hidden>≠</div>
            <div>
              <div className="text-[12px] font-medium text-muted">Found</div>
              <div className="font-semibold text-bad">{failed.found?.length ? failed.found.join(", ") : "nowhere (unknown origin)"}</div>
            </div>
          </motion.div>
        )}

        {ready && d?.one_pass && (
          <motion.div
            key="pass"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            className={cn("mt-3 grid grid-cols-[1fr_auto] overflow-hidden rounded-xl border-[1.5px]", attackerPaid ? "border-bad" : "border-ok")}
          >
            <div className="min-w-0 p-3">
              <div className={cn("flex items-center gap-1.5 text-[12px] font-semibold", attackerPaid ? "text-bad" : "text-ok")}>
                <Ticket className="size-3.5" aria-hidden /> One-time pass · {d.one_pass.pass_id}
              </div>
              <div className="truncate font-mono text-[13px]">{inr(d.one_pass.amount_paise)} → {d.one_pass.payee_account} · {d.one_pass.invoice_id}</div>
            </div>
            <div className={cn("grid place-items-center border-l-[1.5px] border-dashed px-4 text-center font-mono text-xs", attackerPaid ? "border-bad bg-bad/5" : "border-ok bg-ok/5")}>
              <b className="text-base">2:00</b>single use
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {ready && latest?.outcome === "STEP_UP" && latest.approval === "pending" && (
        <div className="mt-3 flex justify-center">
          <Button variant="primary" onClick={onReview}>Review the request</Button>
        </div>
      )}
      {note && (
        <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-4 border-l-[3px] border-seal/50 pl-3.5 text-[14.5px] leading-relaxed text-ink/90">
          {note}
        </motion.p>
      )}
    </Card>
  );
}
