"""Environment-driven settings for the gate and payment service.

Read lazily via `load_settings()` (not at import time) so tests can override env vars.
Fails closed: missing, placeholder, or short keys refuse to start the service.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from app.models import GateMode

BACKEND_DIR = Path(__file__).resolve().parent.parent
FIXTURES_DIR = BACKEND_DIR / "fixtures"
DATA_DIR = BACKEND_DIR / "data"

KEY_NAMES = ("MANDATE_KEY", "ROOT_KEY", "PASS_KEY")
PLACEHOLDER_PREFIX = "change-me"
MIN_KEY_CHARS = 32


class ConfigError(RuntimeError):
    pass


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


def _require_key(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or value.startswith(PLACEHOLDER_PREFIX) or len(value) < MIN_KEY_CHARS:
        raise ConfigError(
            f"{name} is missing, a placeholder, or shorter than {MIN_KEY_CHARS} chars. "
            "Run `make setup` to generate keys into .env."
        )
    return value


def _pass_ttl() -> int:
    raw = os.environ.get("PASS_TTL_SECONDS", "120").strip()
    if not raw.isdigit() or not 0 < int(raw) <= 600:
        raise ConfigError("PASS_TTL_SECONDS must be an integer in 1..600")
    return int(raw)


def load_settings() -> Settings:
    mode = os.environ.get("GATE_MODE", "gated")
    if mode not in ("gated", "baseline"):
        mode = "gated"  # fail closed: unknown mode → the protected one
    return Settings(
        mandate_key=_require_key("MANDATE_KEY"),
        root_key=_require_key("ROOT_KEY"),
        pass_key=_require_key("PASS_KEY"),
        pass_ttl_seconds=_pass_ttl(),
        gate_mode=mode,  # type: ignore[arg-type]
        gate_url=os.environ.get("GATE_URL", "http://localhost:8000"),
        pay_url=os.environ.get("PAY_URL", "http://localhost:8001"),
        gate_db_path=Path(os.environ.get("GATE_DB_PATH", DATA_DIR / "gate.db")),
        pay_db_path=Path(os.environ.get("PAY_DB_PATH", DATA_DIR / "payment.db")),
    )
