"""GET /attacks/results: attack-suite metrics for the Attacks page.

STUB: example numbers. Phase 6 serves attacks/results.json written by run_suite.py.
"""

from fastapi import APIRouter

from app import stub_data
from app.models import AttackResults

router = APIRouter(tags=["attacks"])


@router.get("/attacks/results", response_model=AttackResults)
def attack_results() -> AttackResults:
    return stub_data.ATTACK_RESULTS
