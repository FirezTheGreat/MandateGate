import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import { api } from "../api";
import { inr } from "../lib/utils";
import { latestDecision, useRunEvents } from "../store";
import { Button } from "./ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "./ui/dialog";

export function ApprovalModal({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient();
  const latest = latestDecision(useRunEvents());
  const pending = latest?.outcome === "STEP_UP" && latest.approval === "pending";
  const approvals = useQuery({ queryKey: ["approvals"], queryFn: api.approvals, enabled: pending });
  const request = approvals.data?.find((a) => a.decision_id === latest?.decisionId);

  const resolve = useMutation({
    mutationFn: (approve: boolean) => api.resolveApproval(request!.decision_id, approve),
    onSuccess: (d) => {
      queryClient.setQueryData(["decision", d.decision_id], d);
      void queryClient.invalidateQueries({ queryKey: ["approvals"] });
      toast(d.outcome === "ALLOW" ? `Approved: a pass for exactly ${inr(d.proposal.amount_paise)}` : "Denied: nothing will be paid");
      onOpenChange(false);
    },
    onError: () => toast.error("Could not record your decision"),
  });

  return (
    <Dialog open={open && pending && !!request} onOpenChange={onOpenChange}>
      <DialogContent>
        {request && (
          <>
            <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.16em] text-warn">
              <AlertTriangle className="size-4" aria-hidden /> Ask you first
            </div>
            <DialogTitle className="mt-1 font-display text-2xl font-black">Approve {inr(request.amount_paise)}?</DialogTitle>
            <DialogDescription className="mt-1 text-muted">
              The agent wants to pay more than you approved. Everything else checks out.
            </DialogDescription>
            <dl className="my-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
              <dt className="text-muted">Pay</dt><dd className="font-mono font-semibold">{request.payee_account}</dd>
              <dt className="text-muted">Source</dt><dd className="font-semibold">Vendor registry (trusted)</dd>
              <dt className="text-muted">Invoice</dt><dd className="font-mono font-semibold">{request.invoice_id} · amount matches</dd>
              <dt className="text-muted">You approved</dt><dd className="font-mono font-semibold">up to {inr(request.max_amount_paise)}</dd>
              <dt className="text-muted">Requested</dt>
              <dd className="font-mono font-semibold text-warn">{inr(request.amount_paise)} · {inr(request.amount_paise - request.max_amount_paise)} over</dd>
            </dl>
            <div className="flex justify-end gap-2">
              <Button onClick={() => resolve.mutate(false)} disabled={resolve.isPending}>Deny</Button>
              <Button variant="ok" onClick={() => resolve.mutate(true)} disabled={resolve.isPending} autoFocus>
                Approve {inr(request.amount_paise)}
              </Button>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
