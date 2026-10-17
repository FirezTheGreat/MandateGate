"""STUBS still standing after Phase 4: example data for routes whose real implementation is
in a later phase. Built through models.py so the contracts stay validated. Delete it when
its phase lands.

    ATTACK_RESULTS   GET /attacks/results  → Phase 6 (attack suite)
"""

from app.models import AttackCaseResult, AttackResults

TS = "2026-10-17T09:00:00Z"

ATTACK_RESULTS = AttackResults(
    generated_at=TS,
    total_cases=1,
    baseline_asr=1.0,
    gated_asr=0.0,
    benign_fpr=0.0,
    cases=[
        AttackCaseResult(
            id="A01", category="payee_swap_email", scenario="hero_attack", mode="baseline",
            expected="ALLOW", outcomes=["ALLOW"], attacker_paid_runs=1, runs=1,
        ),
        AttackCaseResult(
            id="A01", category="payee_swap_email", scenario="hero_attack", mode="gated",
            expected="BLOCK", outcomes=["BLOCK"], attacker_paid_runs=0, runs=1,
        ),
    ],
)
