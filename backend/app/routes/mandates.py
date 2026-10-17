"""POST /mandates, POST /delegate. STUB: real signing/attenuation lands in Phase 1."""

from fastapi import APIRouter

from app import stub_data
from app.models import DelegateRequest, DelegationToken, Mandate, MandateCreated, MandateCreateRequest

router = APIRouter(tags=["mandates"])


@router.post("/mandates", response_model=MandateCreated)
def create_mandate(req: MandateCreateRequest) -> MandateCreated:
    mandate = Mandate(
        mandate_id="mdt_example",
        principal=req.principal,
        constraints=req.constraints,
        created_at=stub_data.TS,
        expires_at=stub_data.MANDATE.expires_at,
        signature=stub_data.FAKE_SIG,
    )
    token = stub_data.ROOT_TOKEN.model_copy(
        update={
            "caveats": [
                "agent in planner,finance",
                "tool in list_inbox,read_email,get_invoice,get_vendor,propose_payment",
                f"max_amount_paise <= {req.constraints.max_amount_paise}",
            ]
        }
    )
    return MandateCreated(mandate=mandate, token=token)


@router.post("/delegate", response_model=DelegationToken)
def delegate(req: DelegateRequest) -> DelegationToken:
    return DelegationToken(
        token_id="tok_child_example",
        mandate_id=req.token.mandate_id,
        caveats=[*req.token.caveats, *req.caveats],
        parent_token_id=req.token.token_id,
        sig=stub_data.FAKE_SIG,
    )
