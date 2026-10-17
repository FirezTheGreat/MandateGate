import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense, useState } from "react";
import { api } from "./api";
import { useEventStream } from "./hooks/useEventStream";
import { cn } from "./lib/utils";
import Live from "./pages/Live";
import { useLive } from "./store";

const Attacks = lazy(() => import("./pages/Attacks")); // code-split per page

type Page = "live" | "attacks";

function Seal() {
  return (
    <svg width="36" height="36" viewBox="0 0 40 40" aria-hidden>
      <circle cx="20" cy="20" r="18" fill="none" stroke="#86a0ff" strokeWidth="2.5" strokeDasharray="3 2.2" />
      <circle cx="20" cy="20" r="12.5" fill="#86a0ff" />
      <path d="M14.5 20.5l3.6 3.6 7.4-8" fill="none" stroke="#0a0f1e" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function StreamPill() {
  const stream = useLive((s) => s.stream);
  const mode = useQuery({ queryKey: ["mode"], queryFn: api.mode });
  return (
    <div className="flex items-center gap-2 text-xs font-semibold">
      {mode.data && (
        <span className={cn("rounded-full px-2.5 py-1", mode.data.mode === "gated" ? "bg-seal/15 text-seal" : "bg-bad/15 text-bad")}>
          {mode.data.mode === "gated" ? "MandateGate on" : "MandateGate off"}
        </span>
      )}
      <span className="inline-flex items-center gap-1.5 rounded-full bg-panel px-2.5 py-1 text-muted">
        <i className={cn("size-2 rounded-full", stream === "live" ? "bg-ok" : stream === "connecting" ? "bg-warn" : "bg-bad")} />
        {stream === "live" ? "Live" : stream === "connecting" ? "Connecting" : "Gate offline"}
      </span>
    </div>
  );
}

export default function App() {
  const [page, setPage] = useState<Page>("live");
  useEventStream();
  const tab = (p: Page, label: string) => (
    <button
      type="button"
      role="tab"
      aria-selected={page === p}
      onClick={() => setPage(p)}
      className={cn("cursor-pointer rounded-full px-4 py-1.5 text-sm font-semibold", page === p ? "bg-ink text-bg" : "text-muted hover:text-ink")}
    >
      {label}
    </button>
  );

  return (
    <div className="mx-auto flex max-w-375 flex-col gap-4 px-4 py-4 sm:px-6">
      <header className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <div className="flex items-center gap-3">
          <Seal />
          <div>
            <div className="font-display text-2xl font-extrabold leading-none tracking-tight">MandateGate</div>
            <div className="text-[13px] text-muted">The AI suggests. MandateGate decides.</div>
          </div>
        </div>
        <nav role="tablist" aria-label="Pages" className="flex gap-1 rounded-full border border-line bg-panel p-1">
          {tab("live", "Live demo")}
          {tab("attacks", "Attack suite")}
        </nav>
        <div className="ml-auto"><StreamPill /></div>
      </header>
      <main>
        {page === "live" ? <Live /> : (
          <Suspense fallback={<p className="text-muted">Loading…</p>}><Attacks /></Suspense>
        )}
      </main>
    </div>
  );
}
