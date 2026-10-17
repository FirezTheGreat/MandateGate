"""SQLite connection + schemas. One file per service, WAL mode, stdlib sqlite3 only.

JSON blobs are stored as canonical JSON text. Money columns are INTEGER paise and the
schema refuses anything that is not an integer.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic import BaseModel

from app.crypto import canonical_json
from app.models import DelegationToken, Mandate, Receipt

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

-- Provenance store (one row per recorded leaf value of every tool result).
CREATE TABLE IF NOT EXISTS value_records (
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
CREATE INDEX IF NOT EXISTS idx_value_records_lookup ON value_records (session_id, normalized);

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

GATE_TABLES = (
    "mandates",
    "tokens",
    "sessions",
    "tool_calls",
    "value_records",
    "decisions",
    "passes",
    "approvals",
    "events",
)
PAYMENT_TABLES = ("used_nonces", "ledger")


def connect(path: Path) -> sqlite3.Connection:
    """One connection per request/thread. Autocommit mode: multi-statement writes use
    `transaction()` explicitly, so atomicity is visible in the code."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE takes the write lock up front: all-or-nothing, one writer at a time."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def init_gate_db(path: Path) -> None:
    conn = connect(path)
    try:
        conn.executescript(GATE_SCHEMA)
    finally:
        conn.close()


def init_payment_db(path: Path) -> None:
    conn = connect(path)
    try:
        conn.executescript(PAYMENT_SCHEMA)
    finally:
        conn.close()


def to_json(obj: BaseModel | list[str]) -> str:
    if isinstance(obj, BaseModel):
        return canonical_json(obj.model_dump(mode="json")).decode("utf-8")
    return canonical_json(obj).decode("utf-8")


# --------------------------------------------------------------------------- gate: mandates & tokens


def insert_mandate(conn: sqlite3.Connection, m: Mandate) -> None:
    conn.execute(
        "INSERT INTO mandates (mandate_id, principal, body, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (m.mandate_id, m.principal, to_json(m), m.created_at, m.expires_at),
    )


def get_mandate(conn: sqlite3.Connection, mandate_id: str) -> Mandate | None:
    row = conn.execute("SELECT body FROM mandates WHERE mandate_id = ?", (mandate_id,)).fetchone()
    return Mandate.model_validate_json(row["body"]) if row else None


def insert_token(conn: sqlite3.Connection, t: DelegationToken, created_at: str) -> None:
    conn.execute(
        "INSERT INTO tokens (token_id, mandate_id, parent_token_id, caveats, sig, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (t.token_id, t.mandate_id, t.parent_token_id, to_json(t.caveats), t.sig, created_at),
    )


def get_token(conn: sqlite3.Connection, token_id: str) -> DelegationToken | None:
    row = conn.execute("SELECT * FROM tokens WHERE token_id = ?", (token_id,)).fetchone()
    if row is None:
        return None
    return DelegationToken(
        token_id=row["token_id"],
        mandate_id=row["mandate_id"],
        caveats=json.loads(row["caveats"]),
        parent_token_id=row["parent_token_id"],
        sig=row["sig"],
    )


# --------------------------------------------------------------------------- payment service: ledger


def insert_receipt(conn: sqlite3.Connection, r: Receipt) -> None:
    conn.execute(
        "INSERT INTO ledger (receipt_id, pass_id, decision_id, invoice_id, payee_account, amount_paise, currency, paid_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (r.receipt_id, r.pass_id, r.decision_id, r.invoice_id, r.payee_account, r.amount_paise, r.currency, r.paid_at),
    )


def list_ledger(conn: sqlite3.Connection) -> list[Receipt]:
    rows = conn.execute("SELECT * FROM ledger ORDER BY paid_at, rowid").fetchall()
    return [Receipt.model_validate(dict(row)) for row in rows]


def clear_ledger(conn: sqlite3.Connection) -> None:
    """Demo reset. used_nonces is deliberately NOT cleared: a reset must never re-arm a pass."""
    conn.execute("DELETE FROM ledger")


def table_names(path: Path) -> set[str]:
    conn = connect(path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        return {r["name"] for r in rows}
    finally:
        conn.close()
