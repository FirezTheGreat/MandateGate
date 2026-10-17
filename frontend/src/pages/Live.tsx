import { useEffect, useState } from "react";
import { ApprovalModal } from "../components/ApprovalModal";
import { ControlBar } from "../components/ControlBar";
import { EventFeed } from "../components/EventFeed";
import { Ledger } from "../components/Ledger";
import { MandateBar } from "../components/MandateBar";
import { ProvenanceGraph } from "../components/ProvenanceGraph";
import { RunProgress } from "../components/RunProgress";
import { VerdictPanel } from "../components/VerdictPanel";
import { useVerdict } from "../hooks/useVerdict";

export default function Live() {
  const { latest, ready } = useVerdict();
  const pendingId = ready && latest?.outcome === "STEP_UP" && latest.approval === "pending" ? latest.decisionId : null;
  const [approvalOpen, setApprovalOpen] = useState(false);

  useEffect(() => {
    if (pendingId) setApprovalOpen(true); // pop the modal as soon as the gate's verdict has landed
  }, [pendingId]);

  return (
    <div className="flex flex-col gap-4">
      <MandateBar />
      <ControlBar />
      <RunProgress />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)]">
        <ProvenanceGraph />
        <VerdictPanel onReview={() => setApprovalOpen(true)} />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <EventFeed />
        <Ledger />
      </div>
      <ApprovalModal open={approvalOpen} onOpenChange={setApprovalOpen} />
    </div>
  );
}
