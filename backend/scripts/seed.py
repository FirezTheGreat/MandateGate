"""Validate the demo fixtures (vendors, invoices, emails, scenarios) and print a summary.

    python -m scripts.seed

The gate loads fixtures at startup and on POST /admin/reset; run this after editing them
(e.g. while tuning email 1842 in Phase 3) to catch mistakes before the demo does.
"""

import sys

from app.fixtures import FixtureError, load_fixtures


def main() -> int:
    try:
        fx = load_fixtures()
    except FixtureError as e:
        print(f"fixtures invalid: {e}")
        return 1
    print(f"vendors   {sorted(fx.vendors)}")
    print(f"invoices  {sorted(fx.invoices)}")
    print(f"emails    {sorted(fx.emails, key=int)}")
    for name, s in sorted(fx.scenarios.items()):
        print(f"scenario  {name}: inbox {s.inbox}, expected {s.expected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
