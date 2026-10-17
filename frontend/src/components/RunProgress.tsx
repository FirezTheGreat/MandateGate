// The run as a sequence of stages, so the audience always sees what is happening right now
// (including the second or two while the gate launches the agent, and an AI agent's thinking time).
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Check, Loader2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useVerdict } from "../hooks/useVerdict";
import { cn, inr } from "../lib/utils";
import { runPhase, type Stage, type StageState, useLive } from "../store";

const STAGES: { id: Stage; title: string }[] = [
  { id: "mandate", title: "Mandate signed" },
  { id: "gather", title: "Agent gathers facts" },
  { id: "propose", title: "Payment proposed" },
  { id: "check", title: "Gate checks" },
  { id: "verdict", title: "Verdict" },
  { id: "money", title: "Money" },
];

const DECISION_TEXT: Record<string, string> = { BLOCK: "BLOCKED", ALLOW: "ALLOWED", STEP_UP: "ASK YOU FIRST" };

const TONE: Record<StageState, { bar: string; dot: string; text: string }> = {
  todo: { bar: "bg-line", dot: "border-line bg-panel text-faint", text: "text-faint" },
  active: { bar: "skeleton rounded-none", dot: "border-seal bg-seal/10 text-seal", text: "text-ink" },
  done: { bar: "bg-ok", dot: "border-ok bg-ok text-white", text: "text-ink" },
  bad: { bar: "bg-bad", dot: "border-bad bg-bad text-white", text: "text-bad" },
  warn: { bar: "bg-warn", dot: "border-warn bg-warn text-white", text: "text-warn" },
};

function StageIcon({ state, n }: { state: StageState; n: number }) {
  if (state === "active") return <Loader2 className="size-4 animate-spin" aria-hidden />;
  if (state === "done") return <Check className="size-4" strokeWidth={3} aria-hidden />;
  if (state === "bad") return <X className="size-4" strokeWidth={3} aria-hidden />;
  if (state === "warn") return <AlertTriangle className="size-3.5" strokeWidth={2.5} aria-hidden />;
  return <span className="text-[12px] font-semibold">{n}</span>;
}

/** Seconds since `from`, ticking while `running`, frozen once it stops. */
function useElapsed(from: number | null, running: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(id);
  }, [running, from]);
  return from === null ? 0 : Math.max(0, Math.floor((now - from) / 1000));
}

export function RunProgress() {
  const run = useLive((s) => s.run);
  const starting = useLive((s) => s.starting);
  const shown = useLive((s) => s.shown);
  const phase = runPhase(starting, run, shown);
  const decisionId = phase.decision?.decisionId;
  const trace = useQuery({ queryKey: ["trace", decisionId], queryFn: () => api.trace(decisionId!), enabled: !!decisionId });
  const attackerPaid = phase.decision?.outcome === "ALLOW" && trace.data?.fields.find((f) => f.field === "payee_account")?.status === "bad";

  const { ready } = useVerdict();
  const stages = { ...phase.stages };
  if (phase.decision && !ready) {
    stages.check = "active";
    stages.verdict = "todo";
    stages.money = "todo";
  }
  if (ready && attackerPaid) {
    stages.verdict = "bad";
    if (stages.money === "done") stages.money = "bad";
  }

  const from = starting?.at ?? run?.startedAt ?? null;
  const seconds = useElapsed(from, phase.active);
  const waitingForYou = phase.decision?.outcome === "STEP_UP" && phase.decision.approval === "pending";

  const detail: Record<Stage, string> = {
    mandate: starting ? "Signing your approval…" : run ? "Sealed with HMAC" : "Your approval, signed",
    gather: (stages.gather === "warn" || stages.gather === "bad") && !phase.proposal
      ? phase.ended?.detail ?? "Stopped without proposing a payment"
      : stages.gather === "active"
      ? phase.lastTool ? `${phase.lastTool} · ${phase.toolCalls} call${phase.toolCalls === 1 ? "" : "s"}` : "Agent is starting…"
      : phase.toolCalls ? `${phase.toolCalls} tool calls, all via the gate` : "Inbox, invoice, vendor",
    propose: phase.proposal ? `${inr(phase.proposal.amount)} → ${phase.proposal.payee}` : "Payee and amount",
    check: stages.check === "active" ? "Running six checks…" : stages.check === "done" ? "Six checks run" : "Six checks",
    verdict: phase.decision && ready
      ? `${DECISION_TEXT[phase.decision.outcome] ?? phase.decision.outcome}${attackerPaid ? " · attacker's account" : ""}`
      : "Allow, block or ask you",
    money: !ready ? "Only with a valid pass"
      : phase.payment
      ? phase.payment.status === "paid" ? `Paid ${inr(phase.payment.amount)} to ${phase.payment.payee}` : `Refused: ${phase.payment.error ?? "rejected"}`
      : phase.decision?.outcome === "BLOCK" ? "No pass issued: nothing moved"
      : waitingForYou ? "Waiting for your approval"
      : stages.money === "active" ? "Paying with the one-time pass…" : "Only with a valid pass",
  };

  const headline = starting
    ? `Starting ${starting.agent === "llm" ? "the AI agent" : "the simulated fooled agent"}…`
    : run
      ? `${run.agent_label} · ${run.mode === "gated" ? "with" : "without"} MandateGate`
      : "Pick a scenario above to start a run";

  return (
    <section aria-label="Run progress" className="rounded-2xl border border-line bg-panel px-5 pb-4 pt-3.5">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-[14px] font-medium text-muted">
          {phase.active && <span className="mr-2 inline-block size-2 animate-breathe rounded-full bg-seal align-middle" aria-hidden />}
          {headline}
        </div>
        {from !== null && (
          <div className="font-mono text-[13px] text-muted tabular">
            {phase.finished ? "finished in " : waitingForYou ? "waiting · " : ""}{seconds}s
          </div>
        )}
      </div>
      <ol className="grid grid-cols-2 gap-x-3 gap-y-4 sm:grid-cols-3 lg:grid-cols-6">
        {STAGES.map((s, i) => {
          const state = stages[s.id];
          const tone = TONE[state];
          return (
            <li key={s.id} aria-current={state === "active" ? "step" : undefined} className="min-w-0">
              <div className={cn("mb-2.5 h-1 rounded-full transition-colors duration-300", tone.bar)} />
              <div className="flex items-start gap-2.5">
                <span className={cn("grid size-7 shrink-0 place-items-center rounded-full border-[1.5px] transition-colors duration-300", tone.dot)}>
                  <StageIcon state={state} n={i + 1} />
                </span>
                <div className="min-w-0">
                  <div className={cn("text-[14px] font-semibold leading-tight transition-colors", tone.text)}>{s.title}</div>
                  <div className={cn("truncate text-[12.5px]", state === "todo" ? "text-faint" : "text-muted", s.id !== "check" && s.id !== "mandate" && state !== "todo" && "font-mono text-[12px]")} title={detail[s.id]}>
                    {detail[s.id]}
                  </div>
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
