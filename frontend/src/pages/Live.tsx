// Phase 0 wiring proof: renders the stub decision from GET /decisions/dec_example.
// Phase 5 replaces this with MandateBar, ProvenanceGraph, DecisionPanel, EventFeed, etc.
import { useEffect, useState } from "react";
import { getDecision } from "../api";
import type { CheckStatus, Decision, Outcome } from "../types";

const BANNER: Record<Outcome, { text: string; className: string }> = {
  ALLOW: { text: "ALLOWED", className: "bg-green-600" },
  BLOCK: { text: "BLOCKED", className: "bg-red-600" },
  STEP_UP: { text: "ASK YOU FIRST", className: "bg-amber-500" },
};

const MARK: Record<CheckStatus, { symbol: string; className: string }> = {
  pass: { symbol: "✓", className: "text-green-600" },
  fail: { symbol: "✗", className: "text-red-600" },
  skipped: { symbol: "–", className: "text-slate-400" },
};

export default function Live() {
  const [decision, setDecision] = useState<Decision | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDecision("dec_example")
      .then(setDecision)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  if (error) {
    return (
      <div className="rounded border-2 border-red-600 bg-white p-4 text-red-700">
        Could not reach the gate: {error}. Is <code>make dev</code> running?
      </div>
    );
  }
  if (!decision) return <p className="text-slate-500">Loading decision…</p>;

  const banner = BANNER[decision.outcome];
  return (
    <section className="max-w-3xl space-y-4">
      <div className={`rounded px-6 py-4 text-4xl font-black tracking-wide text-white ${banner.className}`}>
        {banner.text}
      </div>
      <p className="text-slate-600">
        Decision <code>{decision.decision_id}</code> ({decision.mode} mode, stub data): pay{" "}
        <b>{decision.proposal.payee_account}</b> ₹{(decision.proposal.amount_paise / 100).toLocaleString("en-IN")}{" "}
        for {decision.proposal.invoice_id}
      </p>
      <ul className="divide-y rounded bg-white shadow">
        {decision.checks.map((c) => (
          <li key={c.check} className="flex gap-4 px-4 py-3">
            <span className={`w-6 text-xl font-bold ${MARK[c.status].className}`}>{MARK[c.status].symbol}</span>
            <div>
              <div className="font-semibold">{c.check}</div>
              {c.detail && <div className="text-slate-600">{c.detail}</div>}
              {c.required && (
                <div className="text-slate-700">
                  Required: <b>{c.required}</b> · Found: <b className="text-red-700">{c.found?.join(", ")}</b>
                </div>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
