"""Gate events: every tool call, critical value, proposal, decision, payment, suspicious input, and
the end of each dashboard run.

Every event is committed to the events table; GET /sessions/{id}/events reads it, and
GET /events/stream (SSE) streams it live (routes/events.py).

`data` shapes (the dashboard relies on these):
    tool_call           {tool_call_id, agent_id, tool, args, status, values_recorded, error?}
    value_recorded      {value_id, raw, field_hint, source_ref, trust}
    proposal            {agent_id, invoice_id, vendor_id, payee_account, amount_paise}
    decision            {decision_id, outcome, mode, failed: [check names], approval?: "pending", via?: "approval"}
    escalation_attempt  {token_id, mandate_id, caveats: [flagged caveats]}
    suspicious_input    {path, fields: [rejected field names]}
    payment             PaymentEventReport: {status: paid|refused, receipt?, error?, detail?, pass_id?,
                        decision_id?, payee_account?, amount_paise?, sent_at} (signed by the payment service)
    run_finished        {exit_code, ok, detail: the run's error line or null} (the runner, when a dashboard run's
                        process exits; display only)
"""

import sqlite3
from typing import Any

from app import db
from app.crypto import new_id
from app.models import EventType


def emit(conn: sqlite3.Connection, type_: EventType, session_id: str | None, data: dict[str, Any], ts: str) -> None:
    db.insert_event(conn, event_id=new_id("evt"), session_id=session_id, type_=type_, data=data, ts=ts)
