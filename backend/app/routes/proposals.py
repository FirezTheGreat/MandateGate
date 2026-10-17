"""POST /proposals (agent-facing name: propose_payment).

STUB: always returns the hero-attack BLOCK decision (echoing the caller's session and
proposal fields). That fails closed by construction, so nothing issued here can ever be
used to pay. Real decide() lands in Phase 2.
"""

from fastapi import APIRouter

from app import stub_data
from app.models import Decision, PaymentProposal, ProposalSummary

router = APIRouter(tags=["proposals"])


@router.post("/proposals", response_model=Decision)
def submit_proposal(proposal: PaymentProposal) -> Decision:
    summary = ProposalSummary(**proposal.model_dump(exclude={"session_id", "token"}))
    return stub_data.DEC_EXAMPLE.model_copy(update={"session_id": proposal.session_id, "proposal": summary})
