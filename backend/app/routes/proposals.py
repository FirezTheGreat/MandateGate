"""POST /proposals (agent-facing name: propose_payment).

STUB: always returns the hero-attack BLOCK decision. That fails closed by construction,
so nothing issued here can ever be used to pay. Real decide() lands in Phase 2.
"""

from fastapi import APIRouter

from app import stub_data
from app.models import Decision, PaymentProposal

router = APIRouter(tags=["proposals"])


@router.post("/proposals", response_model=Decision)
def submit_proposal(_: PaymentProposal) -> Decision:
    return stub_data.DEC_EXAMPLE
