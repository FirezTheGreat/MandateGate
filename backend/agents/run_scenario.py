"""CLI: run a scenario end-to-end.

    python -m agents.run_scenario --scenario hero_attack --mode gated --agent llm

STUB: Phase 3 (Workstream C) implements it. It sets the gate mode, creates the mandate,
runs the planner, pays with the pass on ALLOW, and prints a summary.
"""

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenario", required=True, choices=["happy", "hero_attack", "step_up"])
    parser.add_argument("--mode", default="gated", choices=["gated", "baseline"])
    parser.add_argument("--agent", default="llm", choices=["llm", "scripted"])
    args = parser.parse_args()
    print(f"run_scenario: not implemented yet (Phase 3). Requested {args.scenario} / {args.mode} / {args.agent}.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
