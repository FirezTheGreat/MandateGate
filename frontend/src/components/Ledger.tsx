import { useAutoAnimate } from "@formkit/auto-animate/react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { clock, cn, inr } from "../lib/utils";
import { Badge, Card, CardHeader } from "./ui/card";

export function Ledger() {
  const ledger = useQuery({ queryKey: ["ledger"], queryFn: api.ledger });
  const rows = [...(ledger.data ?? [])].reverse();
  // A row is the attacker's if its payee doesn't trace to the vendor registry (asked of the tracer, not guessed).
  const traces = useQueries({ queries: rows.map((r) => ({ queryKey: ["trace", r.decision_id], queryFn: () => api.trace(r.decision_id), staleTime: Infinity })) });
  const [bodyRef] = useAutoAnimate<HTMLTableSectionElement>();

  return (
    <Card>
      <CardHeader title="Ledger · money that actually moved" />
      <div className="overflow-x-auto">
        <table className="w-full text-[14px] tabular">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wider text-faint">
              <th className="py-1.5 font-semibold">Time</th>
              <th className="font-semibold">Invoice</th>
              <th className="font-semibold">Paid to</th>
              <th className="text-right font-semibold">Amount</th>
              <th className="pl-3 font-semibold">Result</th>
            </tr>
          </thead>
          <tbody ref={bodyRef}>
            {rows.map((r, i) => {
              const payee = traces[i]?.data?.fields.find((f) => f.field === "payee_account");
              const attacker = payee?.status === "bad";
              return (
                <tr key={r.receipt_id} className={cn("border-t border-line/70", attacker && "bg-bad/10")}>
                  <td className="py-2 font-mono text-xs text-muted">{clock(r.paid_at)}</td>
                  <td className="font-mono text-[13px]">{r.invoice_id}</td>
                  <td className={cn("font-mono text-[13px]", attacker && "font-semibold text-bad")}>{r.payee_account}</td>
                  <td className="text-right font-mono text-[13px]">{inr(r.amount_paise)}</td>
                  <td className="pl-3">{payee ? <Badge tone={attacker ? "bad" : "ok"}>{attacker ? "Attacker paid" : "Vendor paid"}</Badge> : null}</td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr><td colSpan={5} className="py-6 text-center text-sm text-muted">No money has moved. Blocked payments never reach this table.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
