import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense, useState } from "react";
import { api } from "./api";
import { Skeleton } from "./components/ui/card";
import { useEventStream } from "./hooks/useEventStream";
import { usePlayback } from "./hooks/usePlayback";
import { useVerdictClock } from "./hooks/useVerdict";
import { cn } from "./lib/utils";
import Live from "./pages/Live";
import { useLive } from "./store";

const Attacks = lazy(() => import("./pages/Attacks")); // code-split per page

type Page = "live" | "attacks";

function Seal() {
  return (
    <svg width="40" height="40" viewBox="0 0 40 40" aria-hidden>
      <circle cx="20" cy="20" r="18.5" fill="none" stroke="#2c4a7e" strokeWidth="1.5" />
      <circle cx="20" cy="20" r="15" fill="none" stroke="#2c4a7e" strokeWidth="1" strokeDasharray="1.5 2.2" />
      <circle cx="20" cy="20" r="11" fill="#2c4a7e" />
      <path d="M15 20.3l3.4 3.4 6.8-7.4" fill="none" stroke="#fffdf9" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function StreamPill() {
  const stream = useLive((s) => s.stream);
  const mode = useQuery({ queryKey: ["mode"], queryFn: api.mode });
  return (
    <div className="flex items-center gap-2 text-[13px] font-semibold">
      {mode.data ? (
        <span className={cn("rounded-full px-3 py-1", mode.data.mode === "gated" ? "bg-seal/10 text-seal" : "bg-bad/10 text-bad")}>
          {mode.data.mode === "gated" ? "MandateGate on" : "MandateGate off"}
        </span>
      ) : (
        <Skeleton className="h-7 w-32 rounded-full" />
      )}
      <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-panel px-3 py-1 text-muted">
        <i className={cn("size-2 rounded-full", stream === "live" ? "bg-ok" : stream === "connecting" ? "animate-breathe bg-warn" : "bg-bad")} />
        {stream === "live" ? "Live" : stream === "connecting" ? "Connecting" : "Gate offline"}
      </span>
    </div>
  );
}

function PageFallback() {
  return (
    <div className="flex flex-col gap-4" aria-busy>
      <Skeleton className="h-9 w-2/3" />
      <div className="grid gap-4 md:grid-cols-3">
        {[0, 1, 2].map((i) => <Skeleton key={i} className="h-36 rounded-2xl" />)}
      </div>
      <Skeleton className="h-80 rounded-2xl" />
    </div>
  );
}

/** Drives the run's playback and the checklist clock. Its own component, so the event-by-event
 *  updates it subscribes to re-render nothing but itself. */
function Conductor() {
  usePlayback();
  useVerdictClock();
  return null;
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
      className={cn("cursor-pointer rounded-full px-4 py-1.5 text-sm font-semibold transition-colors", page === p ? "bg-ink text-white" : "text-muted hover:text-ink")}
    >
      {label}
    </button>
  );

  return (
    <div className="mx-auto flex max-w-375 flex-col gap-5 px-4 py-5 sm:px-6">
      <header className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <div className="flex items-center gap-3">
          <Seal />
          <div>
            <div className="font-display text-[28px] font-bold leading-none">MandateGate</div>
            <div className="mt-1 text-[13px] text-muted">The AI suggests. <i className="font-display text-[14px] text-ink">MandateGate decides.</i></div>
          </div>
        </div>
        <nav role="tablist" aria-label="Pages" className="flex gap-1 rounded-full border border-line bg-panel p-1">
          {tab("live", "Live demo")}
          {tab("attacks", "Attack suite")}
        </nav>
        <div className="ml-auto"><StreamPill /></div>
      </header>
      <Conductor />
      <main>
        {page === "live" ? <Live /> : (
          <Suspense fallback={<PageFallback />}><Attacks /></Suspense>
        )}
      </main>
    </div>
  );
}
