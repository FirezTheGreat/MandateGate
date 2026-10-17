import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, FlaskConical, Loader2, Play, RotateCcw } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { api, ApiError } from "../api";
import { cn } from "../lib/utils";
import { runPhase, useLive } from "../store";
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
  const run = useLive((s) => s.run);
  const starting = useLive((s) => s.starting);
  const shown = useLive((s) => s.shown);
  const beginStart = useLive((s) => s.beginStart);
  const cancelStart = useLive((s) => s.cancelStart);
  const startRun = useLive((s) => s.startRun);
  const addEvents = useLive((s) => s.addEvents);
  const clear = useLive((s) => s.clear);
  const [realAiForScam, setRealAiForScam] = useState(false);
  const mode = useQuery({ queryKey: ["mode"], queryFn: api.mode });
  const phase = runPhase(starting, run, shown);

  const setMode = useMutation({
    mutationFn: (m: GateMode) => api.setMode(m),
    onSuccess: (s) => {
      queryClient.setQueryData(["mode"], s);
      toast(s.mode === "gated" ? "MandateGate is on" : "MandateGate is off: ordinary access checks only");
    },
    onError: () => toast.error("Could not switch protection"),
  });

  const agentFor = (s: ScenarioCard): AgentMode => (s.id === "hero_attack" && realAiForScam ? "llm" : s.agent);

  const start = useMutation({
    mutationFn: (s: ScenarioCard) => api.runScenario(s.id, agentFor(s)),
    onMutate: (s) => beginStart(s.id, agentFor(s)), // show progress at once: launching the agent takes a second or two
    onSuccess: async (r) => {
      // Load what the run already emitted before following it, so the pacer replays it in order.
      addEvents(await api.sessionEvents(r.session_id).catch(() => []));
      startRun(r);
    },
    onError: (e) => {
      cancelStart();
      toast.error(e instanceof ApiError && e.body ? e.body.detail : "Could not start the scenario");
    },
  });

  const reset = useMutation({
    mutationFn: api.resetAll,
    onSuccess: async () => {
      clear();
      // The wiped decisions no longer exist: drop them instead of refetching them into 404s.
      queryClient.setQueryData(["ledger"], []);
      queryClient.removeQueries({ queryKey: ["trace"] });
      queryClient.removeQueries({ queryKey: ["decision"] });
      await queryClient.invalidateQueries();
      toast("Reset: gate state and ledger cleared");
    },
    onError: () => toast.error("Reset failed: is the gate running?"),
  });

  const current = mode.data?.mode ?? "gated";
  const watching = starting?.scenario ?? run?.scenario;
  return (
    <section className="flex flex-wrap items-stretch gap-4">
      <div className="flex flex-col justify-center gap-1.5">
        <span className="text-[13px] font-medium text-muted">Protection</span>
        <Segmented<GateMode>
          label="Protection"
          value={setMode.isPending && setMode.variables ? setMode.variables : current}
          onChange={(m) => m !== current && setMode.mutate(m)}
          disabled={setMode.isPending || !!starting}
          pending={setMode.isPending ? setMode.variables : null}
          options={[
            { value: "baseline", label: "Without MandateGate", activeClass: "bg-bad text-white hover:text-white" },
            { value: "gated", label: "With MandateGate", activeClass: "bg-seal text-white hover:text-white" },
          ]}
        />
      </div>

      <div className="grid min-w-0 flex-1 grid-cols-1 gap-2.5 sm:grid-cols-3">
        {SCENARIOS.map((s) => {
          const agent = agentFor(s);
          const active = watching === s.id;
          const busy = active && phase.active;
          return (
            <button
              key={s.id}
              type="button"
              disabled={!!starting}
              aria-busy={busy}
              onClick={() => start.mutate(s)}
              className={cn(
                "group relative cursor-pointer overflow-hidden rounded-2xl border bg-panel px-4 py-3 text-left transition-[border-color,box-shadow,opacity] hover:border-seal/60 hover:shadow-[0_6px_18px_-12px_rgba(44,74,126,0.5)] disabled:cursor-not-allowed disabled:opacity-55 aria-busy:cursor-progress aria-busy:opacity-100",
                active ? "border-seal shadow-[0_0_0_1px_var(--color-seal)]" : "border-line",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold">{s.title}</span>
                {busy ? (
                  <span className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-seal">
                    <Loader2 className="size-3.5 animate-spin" aria-hidden /> {starting ? "Starting" : "Running"}
                  </span>
                ) : (
                  <Play className="size-4 text-seal opacity-60 transition-opacity group-hover:opacity-100" aria-hidden />
                )}
              </div>
              <div className="truncate text-[13px] text-muted">{s.blurb}</div>
              <div className={cn("mt-1.5 inline-flex items-center gap-1 text-[12px] font-semibold", agent === "llm" ? "text-seal" : "text-warn")}>
                {agent === "llm" ? <Bot className="size-3.5" aria-hidden /> : <FlaskConical className="size-3.5" aria-hidden />}
                {agent === "llm" ? "Real AI agent" : "Simulated fooled agent"}
              </div>
              {busy && <span aria-hidden className="skeleton absolute inset-x-0 bottom-0 h-0.75 rounded-none" />}
            </button>
          );
        })}
      </div>

      <div className="flex flex-col justify-between gap-2">
        <label className="flex cursor-pointer items-center gap-2 text-[13px] text-muted">
          <input id="real-ai-scam" type="checkbox" checked={realAiForScam} onChange={(e) => setRealAiForScam(e.target.checked)} className="size-4 accent-[#2c4a7e]" />
          Real AI for the scam
        </label>
        <Button variant="ghost" size="sm" onClick={() => reset.mutate()} disabled={reset.isPending}>
          {reset.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <RotateCcw className="size-4" aria-hidden />} Reset demo
        </Button>
      </div>
    </section>
  );
}
