"""Reset both services: POST {GATE_URL}/admin/reset and POST {PAY_URL}/reset."""

import os
import sys

import httpx


def main() -> int:
    targets = [
        ("gate", os.environ.get("GATE_URL", "http://localhost:8000") + "/admin/reset"),
        ("payment service", os.environ.get("PAY_URL", "http://localhost:8001") + "/reset"),
    ]
    failed = False
    for name, url in targets:
        try:
            r = httpx.post(url, timeout=5)
            print(f"{name}: {r.status_code} {r.text}")
            failed |= r.status_code != 200
        except httpx.HTTPError as e:
            print(f"{name}: unreachable at {url} ({e.__class__.__name__}). Is `make dev` running?")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
