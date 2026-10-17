import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { api } from "../api";
import { cn, inr, VENDOR_NAMES } from "../lib/utils";
import { useLive } from "../store";
import { Skeleton } from "./ui/card";

export function MandateBar() {
  const run = useLive((s) => s.run);
  const starting = useLive((s) => s.starting);
  const session = useQuery({ queryKey: ["session", run?.session_id], queryFn: () => api.session(run!.session_id), enabled: !!run });
  const mandate = useQuery({
    queryKey: ["mandate", session.data?.mandate_id], queryFn: () => api.mandate(session.data!.mandate_id), enabled: !!session.data,
  });
  const m = mandate.data;
  const c = m?.constraints;
  const loading = !!starting || (!!run && !m);

  return (
    <section
      aria-label="What you authorised"
      aria-busy={loading}
      className="relative flex flex-wrap items-center gap-x-10 gap-y-3 overflow-hidden rounded-2xl border border-line bg-panel py-4 pl-7 pr-5"
    >
      <span aria-hidden className={cn("absolute inset-y-0 left-0 w-1.5 transition-colors duration-500", m ? "bg-seal" : "bg-line")} />
      <div className="min-w-0">
        <div className="text-[13px] font-medium text-muted">You authorised</div>
        {loading ? (
          <div className="mt-1 flex items-center gap-3">
            <Skeleton className="h-6 w-72" />
            <span className="text-[13px] text-muted">{starting ? "Signing a new mandate…" : "Loading the mandate…"}</span>
          </div>
        ) : (
          <div className="font-display text-[23px] font-semibold leading-snug">
            {c ? <>Pay {VENDOR_NAMES[c.vendor_id] ?? c.vendor_id}’s invoice <span className="whitespace-nowrap">{c.invoice_id}</span></> : "Nothing yet: run a scenario to create an approval"}
          </div>
        )}
      </div>
      {(c || loading) && (
        <dl className="flex flex-wrap gap-x-8 gap-y-2">
          {[
            ["Invoice", c?.invoice_id],
            ["Up to", c && inr(c.max_amount_paise)],
            ["Payee must come from", c && "Vendor registry"],
            ["Approved by", m?.principal],
          ].map(([k, v]) => (
            <div key={k}>
              <dt className="text-[12px] text-faint">{k}</dt>
              <dd className="font-semibold tabular">{v ?? <Skeleton className="mt-1 h-5 w-20" />}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className={cn("ml-auto flex items-center gap-2.5 rounded-xl border px-3.5 py-2 transition-colors duration-500", m ? "border-ok/40 bg-ok/5" : "border-dashed border-line")}>
        <ShieldCheck className={cn("size-5", m ? "text-ok" : "text-faint")} aria-hidden />
        <div>
          <div className="text-[13px] font-semibold">{m ? "Sealed by MandateGate" : loading ? "Signing…" : "Not signed yet"}</div>
          <div className="font-mono text-[11.5px] text-muted">HMAC-SHA-256{m ? ` · ${m.signature.slice(0, 6)}…${m.signature.slice(-4)}` : ""}</div>
        </div>
      </div>
    </section>
  );
}
