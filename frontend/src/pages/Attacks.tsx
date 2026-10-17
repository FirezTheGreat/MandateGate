// Attack suite page: the measured results of `make attacks` (backend/attacks/results.json).
// Nothing here is computed beyond counting runs; every number comes from the suite file.
import { useQuery } from "@tanstack/react-query";
import { motion } from "motion/react";
import { useState } from "react";
import { ApiError, api } from "../api";
import { Badge, Card, CardHeader, type Tone } from "../components/ui/card";
import { Segmented } from "../components/ui/segmented";
import type { AttackCaseResult, AttackResults, GateMode, SuiteMetrics, SuiteRun } from "../types";

type ContentAgent = "scripted" | "llm";

const utc = (iso: string) => iso.replace("T", " ").replace(/:\d\dZ$/, " UTC");
const pct = (x: number | null | undefined) => (x == null ? "n/a" : `${Math.round(x * 100)}%`);
const runs = (cases: AttackCaseResult[]) => cases.flatMap((c) => c.runs).filter((r) => r.outcome !== "ERROR");
// Disguised accounts carry invisible characters; show them instead of hiding them.
const visible = (s: string) => s.replace(/[­​-‍⁠﻿]/g, (ch) => `\\u${ch.charCodeAt(0).toString(16).padStart(4, "0")}`);

function chip(c: AttackCaseResult, r: SuiteRun): { tone: Tone; label: string } {
  switch (r.outcome) {
    case "ERROR": return { tone: "neutral", label: "Run failed" };
    case "NO_PROPOSAL": return { tone: "neutral", label: "Agent didn't pay" };
    case "PAID": return { tone: "bad", label: "Accepted" };
    case "REJECTED": return { tone: "ok", label: "Rejected" };
    case "STEP_UP": return { tone: "warn", label: "Asks you" };
    case "BLOCK": return r.false_positive ? { tone: "bad", label: "Wrongly blocked" } : { tone: "ok", label: "Blocked" };
    case "ALLOW":
      if (r.succeeded) return { tone: "bad", label: "Attacker paid" };
      return c.kind === "attack" ? { tone: "seal", label: "Paid real vendor" } : { tone: "ok", label: "Paid" };
  }
}

function runTitle(r: SuiteRun): string {
  const proposal = r.payee_account != null ? `proposed ${r.amount_paise != null ? `₹${(r.amount_paise / 100).toLocaleString("en-IN")}` : ""} to ${visible(r.payee_account)}` : "";
  return [proposal, r.detail && visible(r.detail)].filter(Boolean).join(" · ");
}

function Runs({ c }: { c: AttackCaseResult | undefined }) {
  if (!c) return <span className="text-faint">n/a</span>;
  return (
    <div className="flex flex-wrap items-center gap-1">
      {c.runs.map((r, i) => {
        const { tone, label } = chip(c, r);
        return <Badge key={i} tone={tone} className="cursor-help"><span title={runTitle(r)}>{label}</span></Badge>;
      })}
      {c.agent === "llm" && c.kind === "attack" && (
        <span className="text-xs text-muted">fooled {c.fooled_runs}/{c.runs.length}</span>
      )}
    </div>
  );
}

function Bar({ label, value, hits, total, tone }: { label: string; value: number | null; hits: number; total: number; tone: "bad" | "ok" }) {
  const width = value == null ? 0 : Math.max(value * 100, value > 0 ? 2 : 0);
  const text = tone === "ok" ? "text-ok" : value ? "text-bad" : "text-ink"; // a red 0% would say the opposite of the number
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-semibold">{label}</span>
        <span className="tabular text-sm text-muted">{hits} of {total} runs</span>
      </div>
      <div className="mt-1 flex items-center gap-3">
        <div className="h-3 flex-1 overflow-hidden rounded-full bg-panel-2">
          <motion.div
            className={tone === "bad" ? "h-full rounded-full bg-bad" : "h-full rounded-full bg-ok"}
            initial={{ width: 0 }}
            animate={{ width: `${width}%` }}
            transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
          />
        </div>
        <span className={`font-display tabular w-24 text-right text-4xl font-black font-stretch-118% ${text}`}>
          {pct(value)}
        </span>
      </div>
    </div>
  );
}

function Headline({ m, cases }: { m: SuiteMetrics; cases: AttackCaseResult[] }) {
  const attacks = (mode: GateMode) => runs(cases.filter((c) => c.kind === "attack" && c.mode === mode));
  const base = attacks("baseline");
  const gated = attacks("gated");
  const benign = runs(cases.filter((c) => c.kind === "benign" && c.mode === "gated"));
  const fooled = [...base, ...gated];
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader title="Attacks that got the attacker paid" aside={<Badge tone="seal">Target with MandateGate: 0%</Badge>} />
        <div className="flex flex-col gap-4">
          <Bar label="Without MandateGate" value={m.baseline_asr} hits={base.filter((r) => r.succeeded).length} total={base.length} tone="bad" />
          <Bar label="With MandateGate" value={m.gated_asr} hits={gated.filter((r) => r.succeeded).length} total={gated.length} tone="ok" />
        </div>
        <p className="mt-5 border-t border-line/70 pt-3 text-sm text-muted">
          Same agent, same inbox, same tools. “Without” is the gate with its payee and amount provenance checks switched off, so
          a proposal passes on the mandate and token alone.{" "}
          {m.agent === "llm"
            ? "When the model is not fooled, both modes simply pay the real vendor: MandateGate stays out of the way. Its guarantee does not depend on the model being careful."
            : "A swapped invoice is caught even without them, by the mandate's invoice check."}
        </p>
      </Card>
      <div className="flex flex-col gap-4">
        <Card>
          <div className="text-sm font-semibold text-muted">Legit payments wrongly blocked</div>
          <div className="font-display tabular my-1 text-5xl font-black text-ok font-stretch-118%">{pct(m.benign_fpr)}</div>
          <div className="text-sm text-muted">{benign.filter((r) => r.false_positive).length} of {benign.length} normal and over-the-limit runs, with MandateGate on.</div>
        </Card>
        <Card>
          <div className="text-sm font-semibold text-muted">Agent fell for the attack</div>
          <div className="font-display tabular my-1 text-5xl font-black text-ink font-stretch-118%">{pct(m.fooled_rate)}</div>
          <div className="text-sm text-muted">
            {m.agent === "scripted"
              ? "By design: the simulated agent is scripted to trust the latest message, so every attack is really tested."
              : `${fooled.filter((r) => r.fooled).length} of ${fooled.length} attack runs proposed the attacker's account, amount or invoice.`}
          </div>
        </Card>
      </div>
    </div>
  );
}

function CaseTable({ cases }: { cases: AttackCaseResult[] }) {
  const ids = [...new Set(cases.map((c) => c.id))];
  const find = (id: string, mode: GateMode) => cases.find((c) => c.id === id && c.mode === mode);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-180 table-fixed text-[14px]">
        <colgroup><col className="w-16" /><col className="w-[34%]" /><col /><col /></colgroup>
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wider text-faint">
            <th className="py-1.5 pr-3 font-semibold">Case</th>
            <th className="pr-3 font-semibold">Attack</th>
            <th className="pr-3 font-semibold">Without MandateGate</th>
            <th className="font-semibold">With MandateGate</th>
          </tr>
        </thead>
        <tbody>
          {ids.map((id) => {
            const c = (find(id, "gated") ?? find(id, "baseline"))!;
            return (
              <tr key={id} className="border-t border-line/70 align-top">
                <td className="py-2.5 pr-3 font-mono text-[13px] text-muted">{id}</td>
                <td className="py-2.5 pr-3">
                  <div className="font-semibold">{c.title}</div>
                  <div className="text-[13px] text-muted">{c.how}</div>
                </td>
                <td className="py-2.5 pr-3"><Runs c={find(id, "baseline")} /></td>
                <td className="py-2.5"><Runs c={find(id, "gated")} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Protocol({ cases, m }: { cases: AttackCaseResult[]; m: SuiteMetrics | undefined }) {
  if (!cases.length) return null;
  const rejected = runs(cases).filter((r) => !r.succeeded).length;
  return (
    <Card>
      <CardHeader
        title="Attacks on the token, the pass and the payment rail (no agent)"
        aside={<Badge tone={m?.gated_asr ? "bad" : "ok"}>{rejected} of {runs(cases).length} stopped</Badge>}
      />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {cases.map((c) => {
          const r = c.runs[0];
          if (!r) return null;
          const { tone, label } = chip(c, r);
          return (
            <div key={c.id} className="rounded-xl border border-line bg-panel-2/60 p-3">
              <div className="flex items-start justify-between gap-2">
                <span className="font-mono text-[12px] text-faint">{c.id}</span>
                <Badge tone={tone}>{label}</Badge>
              </div>
              <div className="mt-1 font-semibold leading-snug">{c.title}</div>
              <div className="text-[13px] text-muted">{c.how}</div>
              {r.detail && <div className="mt-2 font-mono text-[12px] text-muted">{visible(r.detail)}</div>}
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function Results({ data }: { data: AttackResults }) {
  const contentAgents = data.metrics.filter((m): m is SuiteMetrics & { agent: ContentAgent } => m.agent !== "protocol");
  const [picked, setPicked] = useState<ContentAgent>("scripted");
  const agent = contentAgents.some((m) => m.agent === picked) ? picked : contentAgents[0]?.agent;
  const m = contentAgents.find((x) => x.agent === agent);
  const mine = data.cases.filter((c) => c.agent === agent);
  const protocol = data.cases.filter((c) => c.agent === "protocol");
  return (
    <>
      {contentAgents.length > 1 && (
        <Segmented<ContentAgent>
          label="Agent"
          value={agent ?? "scripted"}
          onChange={setPicked}
          options={contentAgents.map((x) => ({ value: x.agent, label: x.label }))}
        />
      )}
      {m && <Headline m={m} cases={mine} />}
      {m && (
        <Card>
          <CardHeader
            title={`Every case · ${m.label}`}
            aside={<span className="text-xs text-muted">{m.agent === "llm" ? "3 runs per case, as measured" : "1 run per case (deterministic)"} · hover a result for details</span>}
          />
          <CaseTable cases={mine.filter((c) => c.kind === "attack")} />
          <div className="mt-4 mb-1 text-[11px] font-bold uppercase tracking-[0.12em] text-faint">Benign controls: must still pay (or ask you)</div>
          <CaseTable cases={mine.filter((c) => c.kind === "benign")} />
        </Card>
      )}
      <Protocol cases={protocol} m={data.metrics.find((x) => x.agent === "protocol")} />
      <p className="text-[13px] text-faint">
        Generated {utc(data.generated_at)} · {data.total_cases} cases · {data.total_runs} runs
        {data.model && data.llm_generated_at && <> · AI agent {data.model}, runs from {utc(data.llm_generated_at)}</>}. “Without MandateGate” is baseline mode: the
        same gate with its payee and amount provenance checks switched off. Re-run with <code className="font-mono">make attacks</code>{" "}
        (<code className="font-mono">LLM=1</code> adds the AI agent).
      </p>
    </>
  );
}

export default function Attacks() {
  const q = useQuery({ queryKey: ["attack-results"], queryFn: api.attackResults, retry: false });
  const missing = q.error instanceof ApiError && q.error.status === 404;
  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="text-[11px] font-bold uppercase tracking-[0.16em] text-seal">Measurable results</div>
        <h1 className="font-display text-3xl font-black">Every attack, with and without MandateGate</h1>
        <p className="max-w-3xl text-muted">
          Each scam runs twice through the same agent and tools: once with ordinary access control only, once through MandateGate.
          The simulated agent always falls for the scam, so each attack is really tested. The real AI agent runs each case three
          times, and the page reports what actually happened.
        </p>
      </div>
      {q.isPending && <p className="text-muted">Loading results…</p>}
      {missing && (
        <Card>
          <CardHeader title="No results yet" />
          <p className="text-muted">Run <code className="font-mono text-ink">make attacks</code> to measure the suite. It takes a few seconds.</p>
        </Card>
      )}
      {q.error && !missing && <Card><p className="text-bad">Could not load results: {q.error.message}</p></Card>}
      {q.data && <Results data={q.data} />}
    </div>
  );
}
