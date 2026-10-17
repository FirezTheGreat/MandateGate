import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { api } from "../api";
import { cn, inr, VENDOR_NAMES } from "../lib/utils";
import { useLive } from "../store";

export function MandateBar() {
  const run = useLive((s) => s.run);
  const session = useQuery({ queryKey: ["session", run?.session_id], queryFn: () => api.session(run!.session_id), enabled: !!run });
  const mandate = useQuery({
    queryKey: ["mandate", session.data?.mandate_id], queryFn: () => api.mandate(session.data!.mandate_id), enabled: !!session.data,
  });
  const m = mandate.data;
  const c = m?.constraints;

  return (
    <section aria-label="What you authorised" className="flex flex-wrap items-center gap-x-8 gap-y-3 rounded-2xl border border-line bg-band px-5 py-4">
      <div>
        <div className="text-[11px] font-bold uppercase tracking-[0.16em] text-faint">You authorised</div>
        <div className="font-display text-xl font-bold">
          {c ? `Pay ${VENDOR_NAMES[c.vendor_id] ?? c.vendor_id}'s invoice ${c.invoice_id}` : "Nothing yet: run a scenario to create an approval"}
        </div>
      </div>
      {c && (
        <dl className="flex flex-wrap gap-x-7 gap-y-2">
          {[
            ["Invoice", c.invoice_id],
            ["Up to", inr(c.max_amount_paise)],
            ["Payee must come from", "Vendor registry"],
            ["Approved by", m.principal],
          ].map(([k, v]) => (
            <div key={k}>
              <dt className="text-[11px] uppercase tracking-wider text-faint">{k}</dt>
              <dd className="font-semibold tabular">{v}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className={cn("ml-auto flex items-center gap-2.5 rounded-xl border px-3 py-2", m ? "border-ok/60" : "border-line opacity-60")}>
        <ShieldCheck className={cn("size-5", m ? "text-ok" : "text-faint")} aria-hidden />
        <div>
          <div className="text-xs font-semibold">{m ? "Sealed by MandateGate" : "Not signed yet"}</div>
          <div className="font-mono text-[11px] text-muted">HMAC-SHA-256{m ? ` · ${m.signature.slice(0, 6)}…${m.signature.slice(-4)}` : ""}</div>
        </div>
      </div>
    </section>
  );
}
