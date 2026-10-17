"""Environment-driven settings for the gate and payment service.

Read lazily via `load_settings()` (not at import time) so tests can override env vars.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from app.models import GateMode

BACKEND_DIR = Path(__file__).resolve().parent.parent
FIXTURES_DIR = BACKEND_DIR / "fixtures"
DATA_DIR = BACKEND_DIR / "data"


@dataclass(frozen=True)
class Settings:
    mandate_key: str
    root_key: str
    pass_key: str
    pass_ttl_seconds: int
    gate_mode: GateMode
    gate_url: str
    pay_url: str
    gate_db_path: Path
    pay_db_path: Path


def load_settings() -> Settings:
    mode = os.environ.get("GATE_MODE", "gated")
    if mode not in ("gated", "baseline"):
        mode = "gated"  # fail closed: unknown mode → the protected one
    return Settings(
        mandate_key=os.environ.get("MANDATE_KEY", ""),
        root_key=os.environ.get("ROOT_KEY", ""),
        pass_key=os.environ.get("PASS_KEY", ""),
        pass_ttl_seconds=int(os.environ.get("PASS_TTL_SECONDS", "120")),
        gate_mode=mode,  # type: ignore[arg-type]
        gate_url=os.environ.get("GATE_URL", "http://localhost:8000"),
        pay_url=os.environ.get("PAY_URL", "http://localhost:8001"),
        gate_db_path=Path(os.environ.get("GATE_DB_PATH", DATA_DIR / "gate.db")),
        pay_db_path=Path(os.environ.get("PAY_DB_PATH", DATA_DIR / "payment.db")),
    )
