import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, FlaskConical, Play, RotateCcw } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { api, ApiError } from "../api";
import { cn } from "../lib/utils";
import { useLive } from "../store";
import type { AgentMode, GateMode } from "../types";
import { Button } from "./ui/button";
import { Segmented } from "./ui/segmented";

interface ScenarioCard {
  id: string;
  title: string;
  blurb: string;
  agent: AgentMode; // demo rule (CLAUDE.md §8): the scam runs on the simulated fooled agent
}

const SCENARIOS: ScenarioCard[] = [
  { id: "happy", title: "Legit payment", blurb: "Invoice reminder and a newsletter in the inbox", agent: "llm" },
  { id: "hero_attack", title: "Scam email", blurb: "A look-alike domain asks to pay EVE-777", agent: "scripted" },
  { id: "step_up", title: "Over the limit", blurb: "A ₹5,200 invoice against a ₹5,000 approval", agent: "llm" },
];

export function ControlBar() {
  const queryClient = useQueryClient();
  const { run, startRun, addEvents, clear } = useLive();
  const [realAiForScam, setRealAiForScam] = useState(false);
  const mode = useQuery({ queryKey: ["mode"], queryFn: api.mode });

  const setMode = useMutation({
    mutationFn: (m: GateMode) => api.setMode(m),
    onSuccess: (s) => {
      queryClient.setQueryData(["mode"], s);
      toast(s.mode === "gated" ? "MandateGate is on" : "MandateGate is off: ordinary access checks only");
    },
  });

  const start = useMutation({
    mutationFn: (s: ScenarioCard) => api.runScenario(s.id, s.id === "hero_attack" && realAiForScam ? "llm" : s.agent),
    onSuccess: async (r) => {
      startRun(r);
      toast.info(`Running "${SCENARIOS.find((s) => s.id === r.scenario)?.title}"`, { description: `${r.agent_label} · ${r.mode === "gated" ? "with" : "without"} MandateGate` });
      addEvents(await api.sessionEvents(r.session_id)); // anything emitted before the stream caught up
    },
    onError: (e) => toast.error(e instanceof ApiError && e.body ? e.body.detail : "Could not start the scenario"),
  });

  const reset = useMutation({
    mutationFn: api.resetAll,
    onSuccess: async () => {
      clear();
      await queryClient.invalidateQueries();
      toast("Reset: gate state and ledger cleared");
    },
  });

  const current = mode.data?.mode ?? "gated";
  return (
    <section className="flex flex-wrap items-stretch gap-3">
      <div className="flex flex-col justify-center gap-1.5">
        <span className="text-[11px] font-bold uppercase tracking-[0.16em] text-faint">Protection</span>
        <Segmented<GateMode>
          label="Protection"
          value={current}
          onChange={(m) => setMode.mutate(m)}
          options={[
            { value: "baseline", label: "Without MandateGate", activeClass: "bg-bad text-bg" },
            { value: "gated", label: "With MandateGate", activeClass: "bg-seal text-seal-ink" },
          ]}
        />
      </div>

      <div className="grid min-w-0 flex-1 grid-cols-1 gap-2 sm:grid-cols-3">
        {SCENARIOS.map((s) => {
          const agent = s.id === "hero_attack" && realAiForScam ? "llm" : s.agent;
          const active = run?.scenario === s.id;
          return (
            <button
              key={s.id}
              type="button"
              disabled={start.isPending}
              onClick={() => start.mutate(s)}
              className={cn(
                "group cursor-pointer rounded-xl border bg-panel px-3.5 py-2.5 text-left transition-colors hover:border-seal disabled:cursor-wait",
                active ? "border-seal" : "border-line",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold">{s.title}</span>
                <Play className="size-4 text-seal opacity-70 transition group-hover:opacity-100" aria-hidden />
              </div>
              <div className="truncate text-[13px] text-muted">{s.blurb}</div>
              <div className={cn("mt-1 inline-flex items-center gap-1 text-[11px] font-semibold", agent === "llm" ? "text-seal" : "text-warn")}>
                {agent === "llm" ? <Bot className="size-3.5" aria-hidden /> : <FlaskConical className="size-3.5" aria-hidden />}
                {agent === "llm" ? "Real AI agent" : "Simulated fooled agent"}
              </div>
            </button>
          );
        })}
      </div>

      <div className="flex flex-col justify-between gap-2">
        <label className="flex cursor-pointer items-center gap-2 text-[13px] text-muted">
          <input id="real-ai-scam" type="checkbox" checked={realAiForScam} onChange={(e) => setRealAiForScam(e.target.checked)} className="accent-[#86a0ff]" />
          Real AI for the scam
        </label>
        <Button variant="ghost" size="sm" onClick={() => reset.mutate()} disabled={reset.isPending}>
          <RotateCcw className="size-4" aria-hidden /> Reset demo
        </Button>
      </div>
    </section>
  );
}
