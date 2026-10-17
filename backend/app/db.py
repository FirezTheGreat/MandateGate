"""SQLite connection + schemas. One file per service, WAL mode, stdlib sqlite3 only.

JSON blobs are stored as canonical JSON text. Money columns are INTEGER paise and the
schema refuses anything that is not an integer.
"""

import sqlite3
from pathlib import Path

GATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS mandates (
    mandate_id   TEXT PRIMARY KEY,
    principal    TEXT NOT NULL,
    body         TEXT NOT NULL,              -- full signed Mandate JSON
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tokens (
    token_id        TEXT PRIMARY KEY,
    mandate_id      TEXT NOT NULL,
    parent_token_id TEXT,
    caveats         TEXT NOT NULL,           -- JSON list[str]
    sig             TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    mandate_id  TEXT,
    scenario    TEXT,
    mode        TEXT NOT NULL CHECK (mode IN ('gated', 'baseline')),
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_calls (
    tool_call_id TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    agent_id     TEXT NOT NULL,
    tool         TEXT NOT NULL,
    args         TEXT NOT NULL,              -- JSON
    result       TEXT,                       -- JSON, NULL on error
    status       TEXT NOT NULL CHECK (status IN ('ok', 'error', 'denied')),
    error        TEXT,
    ts           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls (session_id);

-- Provenance store. "values" is an SQL keyword, so it is always quoted.
CREATE TABLE IF NOT EXISTS "values" (
    value_id     TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    raw          TEXT NOT NULL,
    normalized   TEXT NOT NULL,
    field_hint   TEXT NOT NULL,
    source_type  TEXT NOT NULL CHECK (source_type IN ('vendor_registry', 'invoice_db', 'email', 'web', 'user')),
    source_ref   TEXT NOT NULL,
    trust        TEXT NOT NULL CHECK (trust IN ('trusted', 'untrusted')),
    tool_call_id TEXT NOT NULL,
    agent_id     TEXT NOT NULL,
    ts           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_values_lookup ON "values" (session_id, normalized);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    mandate_id  TEXT,
    outcome     TEXT NOT NULL CHECK (outcome IN ('ALLOW', 'BLOCK', 'STEP_UP')),
    mode        TEXT NOT NULL CHECK (mode IN ('gated', 'baseline')),
    proposal    TEXT NOT NULL,               -- JSON PaymentProposal
    body        TEXT NOT NULL,               -- JSON Decision
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_session ON decisions (session_id);

CREATE TABLE IF NOT EXISTS passes (
    pass_id     TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL UNIQUE,
    body        TEXT NOT NULL,               -- JSON OnePass
    exp         TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    decision_id  TEXT PRIMARY KEY,
    status       TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'denied', 'expired')),
    requested_at TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    resolved_at  TEXT
);

CREATE TABLE IF NOT EXISTS events (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id   TEXT NOT NULL UNIQUE,
    session_id TEXT,
    type       TEXT NOT NULL,
    data       TEXT NOT NULL,                -- JSON
    ts         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events (session_id, seq);
"""

PAYMENT_SCHEMA = """
-- Nonce burn: INSERT conflicts on the PRIMARY KEY → replay (409). Must stay atomic.
CREATE TABLE IF NOT EXISTS used_nonces (
    nonce   TEXT PRIMARY KEY,
    pass_id TEXT NOT NULL,
    used_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger (
    receipt_id    TEXT PRIMARY KEY,
    pass_id       TEXT NOT NULL UNIQUE,
    decision_id   TEXT NOT NULL,
    invoice_id    TEXT NOT NULL,
    payee_account TEXT NOT NULL,
    amount_paise  INTEGER NOT NULL CHECK (typeof(amount_paise) = 'integer' AND amount_paise >= 0),
    currency      TEXT NOT NULL,
    paid_at       TEXT NOT NULL
);
"""

GATE_TABLES = ("mandates", "tokens", "sessions", "tool_calls", "values", "decisions", "passes", "approvals", "events")
PAYMENT_TABLES = ("used_nonces", "ledger")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_gate_db(path: Path) -> None:
    with connect(path) as conn:
        conn.executescript(GATE_SCHEMA)
    conn.close()


def init_payment_db(path: Path) -> None:
    with connect(path) as conn:
        conn.executescript(PAYMENT_SCHEMA)
    conn.close()


def table_names(path: Path) -> set[str]:
    conn = connect(path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        return {r["name"] for r in rows}
    finally:
        conn.close()
