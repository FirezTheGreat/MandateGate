"""SQLite connection + schemas. One file per service, WAL mode, stdlib sqlite3 only.

JSON blobs are stored as canonical JSON text. Money columns are INTEGER paise and the
schema refuses anything that is not an integer.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.crypto import canonical_json
from app.models import Decision, DelegationToken, Event, Mandate, OnePass, Receipt, Session, ValueRecord

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
    mandate_id  TEXT NOT NULL,
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
    proposal    TEXT NOT NULL,               -- JSON ProposalSummary (never the bearer token)
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
    limit_paise  INTEGER NOT NULL CHECK (typeof(limit_paise) = 'integer'),  -- effective limit exceeded
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
    """One connection per request. Autocommit mode: multi-statement writes use
    `transaction()` explicitly, so atomicity is visible in the code.

    check_same_thread=False: FastAPI may open, use and close a request's connection on
    different worker threads. Safe because a connection is never shared between requests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, timeout=10, check_same_thread=False)
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


GATE_SCHEMA_VERSION = 2  # bump when GATE_SCHEMA changes


def init_gate_db(path: Path) -> None:
    """Gate state is disposable demo data (POST /admin/reset wipes it), so a schema version
    change rebuilds the tables instead of migrating them. The payment DB is never rebuilt."""
    conn = connect(path)
    try:
        if conn.execute("PRAGMA user_version").fetchone()[0] != GATE_SCHEMA_VERSION:
            for table in (*GATE_TABLES, "values"):  # "values": pre-v2 name of value_records
                conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        conn.executescript(GATE_SCHEMA)
        conn.execute(f"PRAGMA user_version = {GATE_SCHEMA_VERSION}")
    finally:
        conn.close()


def wipe_gate(conn: sqlite3.Connection) -> None:
    with transaction(conn):
        for table in GATE_TABLES:
            conn.execute(f'DELETE FROM "{table}"')


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


def _dumps(obj: Any) -> str:
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


# --------------------------------------------------------------------------- gate: sessions


def insert_session(conn: sqlite3.Connection, *, session_id: str, mandate_id: str, scenario: str | None, mode: str, created_at: str) -> None:
    conn.execute(
        "INSERT INTO sessions (session_id, mandate_id, scenario, mode, created_at) VALUES (?, ?, ?, ?, ?)",
        (session_id, mandate_id, scenario, mode, created_at),
    )


def get_session(conn: sqlite3.Connection, session_id: str) -> Session | None:
    row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    return Session.model_validate(dict(row)) if row else None


# --------------------------------------------------------------------------- gate: tool calls & provenance


def insert_tool_call(
    conn: sqlite3.Connection, *, tool_call_id: str, session_id: str, agent_id: str, tool: str,
    args: dict[str, Any], result: Any, status: str, error: str | None, ts: str,
) -> None:
    conn.execute(
        "INSERT INTO tool_calls (tool_call_id, session_id, agent_id, tool, args, result, status, error, ts)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (tool_call_id, session_id, agent_id, tool, _dumps(args), None if result is None else _dumps(result), status, error, ts),
    )


def insert_values(conn: sqlite3.Connection, records: list[ValueRecord]) -> None:
    conn.executemany(
        'INSERT INTO value_records (value_id, session_id, raw, normalized, field_hint, source_type, source_ref, trust,'
        " tool_call_id, agent_id, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (r.value_id, r.session_id, r.raw, r.normalized, r.field_hint, r.source_type, r.source_ref, r.trust, r.tool_call_id, r.agent_id, r.ts)
            for r in records
        ],
    )


def session_tool_calls(conn: sqlite3.Connection, session_id: str, until_ts: str | None = None) -> list[dict[str, Any]]:
    """Successful tool calls of a session, in order (optionally only those up to a timestamp)."""
    sql = "SELECT tool_call_id, agent_id, tool, args, ts FROM tool_calls WHERE session_id = ? AND status = 'ok'"
    params: list[Any] = [session_id]
    if until_ts is not None:
        sql += " AND ts <= ?"
        params.append(until_ts)
    return [dict(r) for r in conn.execute(sql + " ORDER BY ts, rowid", params).fetchall()]


def session_values(conn: sqlite3.Connection, session_id: str) -> list[ValueRecord]:
    rows = conn.execute("SELECT * FROM value_records WHERE session_id = ? ORDER BY rowid", (session_id,)).fetchall()
    return [ValueRecord.model_validate(dict(row)) for row in rows]


# --------------------------------------------------------------------------- gate: decisions, passes, approvals


def insert_decision(conn: sqlite3.Connection, d: Decision) -> None:
    conn.execute(
        "INSERT INTO decisions (decision_id, session_id, mandate_id, outcome, mode, proposal, body, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (d.decision_id, d.session_id, d.mandate_id, d.outcome, d.mode, to_json(d.proposal), to_json(d), d.created_at),
    )


def update_decision(conn: sqlite3.Connection, d: Decision) -> None:
    conn.execute("UPDATE decisions SET outcome = ?, body = ? WHERE decision_id = ?", (d.outcome, to_json(d), d.decision_id))


def get_decision(conn: sqlite3.Connection, decision_id: str) -> Decision | None:
    row = conn.execute("SELECT body FROM decisions WHERE decision_id = ?", (decision_id,)).fetchone()
    return Decision.model_validate_json(row["body"]) if row else None


def list_decisions(conn: sqlite3.Connection, limit: int = 100) -> list[Decision]:
    rows = conn.execute("SELECT body FROM decisions ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)).fetchall()
    return [Decision.model_validate_json(row["body"]) for row in rows]


def insert_pass(conn: sqlite3.Connection, p: OnePass, created_at: str) -> None:
    conn.execute(
        "INSERT INTO passes (pass_id, decision_id, body, exp, created_at) VALUES (?, ?, ?, ?, ?)",
        (p.pass_id, p.decision_id, to_json(p), p.exp, created_at),
    )


def insert_approval(conn: sqlite3.Connection, *, decision_id: str, limit_paise: int, requested_at: str, expires_at: str) -> None:
    conn.execute(
        "INSERT INTO approvals (decision_id, status, limit_paise, requested_at, expires_at) VALUES (?, 'pending', ?, ?, ?)",
        (decision_id, limit_paise, requested_at, expires_at),
    )


def get_approval(conn: sqlite3.Connection, decision_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM approvals WHERE decision_id = ?", (decision_id,)).fetchone()


def pending_approvals(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT a.decision_id, a.limit_paise, a.requested_at, a.expires_at, d.body FROM approvals a"
        " JOIN decisions d ON d.decision_id = a.decision_id WHERE a.status = 'pending' ORDER BY a.requested_at"
    ).fetchall()


def resolve_approval(conn: sqlite3.Connection, decision_id: str, status: str, resolved_at: str) -> bool:
    """Compare-and-set from 'pending'. False if someone else resolved it first."""
    cur = conn.execute(
        "UPDATE approvals SET status = ?, resolved_at = ? WHERE decision_id = ? AND status = 'pending'",
        (status, resolved_at, decision_id),
    )
    return cur.rowcount == 1


# --------------------------------------------------------------------------- gate: events


def insert_event(conn: sqlite3.Connection, *, event_id: str, session_id: str | None, type_: str, data: dict[str, Any], ts: str) -> None:
    conn.execute(
        "INSERT INTO events (event_id, session_id, type, data, ts) VALUES (?, ?, ?, ?, ?)",
        (event_id, session_id, type_, _dumps(data), ts),
    )


def _event(r: sqlite3.Row) -> Event:
    return Event(event_id=r["event_id"], seq=r["seq"], type=r["type"], session_id=r["session_id"], ts=r["ts"], data=json.loads(r["data"]))


def events_since(conn: sqlite3.Connection, after_seq: int, session_id: str | None = None, limit: int = 500) -> list[Event]:
    """Events with seq > after_seq, across all sessions (or one), in order: what the SSE stream sends."""
    if session_id is None:
        rows = conn.execute("SELECT * FROM events WHERE seq > ? ORDER BY seq LIMIT ?", (after_seq, limit)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM events WHERE session_id = ? AND seq > ? ORDER BY seq LIMIT ?", (session_id, after_seq, limit)).fetchall()
    return [_event(r) for r in rows]


def max_event_seq(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()[0]


def list_events(conn: sqlite3.Connection, session_id: str | None, after_seq: int = 0) -> list[Event]:
    """Events of one session, or (session_id=None) events not tied to any session."""
    if session_id is None:
        rows = conn.execute("SELECT * FROM events WHERE session_id IS NULL AND seq > ? ORDER BY seq", (after_seq,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM events WHERE session_id = ? AND seq > ? ORDER BY seq", (session_id, after_seq)).fetchall()
    return [
        Event(event_id=r["event_id"], seq=r["seq"], type=r["type"], session_id=r["session_id"], ts=r["ts"], data=json.loads(r["data"]))
        for r in rows
    ]


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
