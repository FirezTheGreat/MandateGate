import { useAutoAnimate } from "@formkit/auto-animate/react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { api } from "../api";
import { useVerdict } from "../hooks/useVerdict";
import { clock, cn, inr } from "../lib/utils";
import { runPhase, useLive, useRunEvents } from "../store";
import { Badge, Card, CardHeader, Skeleton } from "./ui/card";

export function Ledger() {
  const ledger = useQuery({ queryKey: ["ledger"], queryFn: api.ledger });
  const rows = [...(ledger.data ?? [])].reverse();
  // A row is the attacker's if its payee doesn't trace to the vendor registry (asked of the tracer, not guessed).
  const traces = useQueries({ queries: rows.map((r) => ({ queryKey: ["trace", r.decision_id], queryFn: () => api.trace(r.decision_id), staleTime: Infinity, retry: false })) });
  const [bodyRef] = useAutoAnimate<HTMLTableSectionElement>({ duration: 220 });
  const run = useLive((s) => s.run);
  const starting = useLive((s) => s.starting);
  const phase = runPhase(starting, run, useRunEvents());
  const { ready } = useVerdict();
  const paying = ready && phase.stages.money === "active" && phase.proposal;

  return (
    <Card>
      <CardHeader title="Ledger · money that actually moved" aside={ledger.isFetching && !ledger.isLoading ? <Loader2 className="size-4 animate-spin text-faint" aria-label="refreshing" /> : null} />
      <div className="overflow-x-auto">
        <table className="w-full text-[14px] tabular">
          <thead>
            <tr className="text-left text-[12px] text-faint">
              <th className="py-1.5 font-medium">Time</th>
              <th className="font-medium">Invoice</th>
              <th className="font-medium">Paid to</th>
              <th className="text-right font-medium">Amount</th>
              <th className="pl-3 font-medium">Result</th>
            </tr>
          </thead>
          <tbody ref={bodyRef}>
            {paying && (
              <tr key="paying" className="border-t border-line/70 text-muted">
                <td className="py-2"><Loader2 className="size-3.5 animate-spin text-seal" aria-hidden /></td>
                <td colSpan={2} className="text-[13px]">Paying with the one-time pass…</td>
                <td className="text-right font-mono text-[13px]">{inr(phase.proposal!.amount)}</td>
                <td className="pl-3"><Skeleton className="h-5 w-24 rounded-full" /></td>
              </tr>
            )}
            {rows.map((r, i) => {
              const payee = traces[i]?.data?.fields.find((f) => f.field === "payee_account");
              const attacker = payee?.status === "bad";
              return (
                <tr key={r.receipt_id} className={cn("border-t border-line/70 transition-colors", attacker && "bg-bad/6")}>
                  <td className="py-2 font-mono text-xs text-muted">{clock(r.paid_at)}</td>
                  <td className="font-mono text-[13px]">{r.invoice_id}</td>
                  <td className={cn("font-mono text-[13px]", attacker && "font-semibold text-bad")}>{r.payee_account}</td>
                  <td className="text-right font-mono text-[13px]">{inr(r.amount_paise)}</td>
                  <td className="pl-3">
                    {payee ? <Badge tone={attacker ? "bad" : "ok"}>{attacker ? "Attacker paid" : "Vendor paid"}</Badge>
                      : traces[i]?.isError ? <Badge>No trace</Badge> /* the gate was reset after this payment */
                      : <Skeleton className="h-5 w-24 rounded-full" />}
                  </td>
                </tr>
              );
            })}
            {ledger.isLoading && [0, 1].map((i) => (
              <tr key={`sk${i}`} className="border-t border-line/70">
                <td colSpan={5} className="py-2.5"><Skeleton className="h-4 w-full" /></td>
              </tr>
            ))}
            {ledger.isError && (
              <tr key="err"><td colSpan={5} className="py-6 text-center text-sm text-bad">Payment service unreachable on :8001.</td></tr>
            )}
            {ledger.isSuccess && rows.length === 0 && !paying && (
              <tr key="empty"><td colSpan={5} className="py-6 text-center text-sm text-muted">No money has moved. Blocked payments never reach this table.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
