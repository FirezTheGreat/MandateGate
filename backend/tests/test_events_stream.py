"""Live events: the SSE source streams persisted events in order, live, filtered, resumable."""

import asyncio
import json
from typing import Any

from fastapi.testclient import TestClient

from app import db, events
from app.routes.events import event_source
from tests.conftest import Env
from tests.gatekit import GateKit


def collect(env: Env, *, after: int, session_id: str | None = None, n: int, during: Any = None) -> list[dict[str, str]]:
    """Read n SSE messages from the source; `during` runs once the stream is open (to emit live events)."""

    async def main() -> list[dict[str, str]]:
        out: list[dict[str, str]] = []

        async def never() -> bool:
            return False

        def conn():  # type: ignore[no-untyped-def]
            return db.connect(env.gate_db)

        gen = event_source(conn, after=after, session_id=session_id, poll_s=0.01, is_disconnected=never)
        started = False
        async for msg in gen:
            out.append(msg)
            if not started and during is not None:
                started = True
                await asyncio.to_thread(during)
            if len(out) >= n:
                break
        await gen.aclose()
        return out

    return asyncio.run(main())


def test_stream_replays_a_session_in_order(gate: TestClient, env: Env) -> None:
    kit = GateKit(gate)
    sid, tok = kit.start()
    kit.investigate(sid, tok)
    kit.propose(sid, tok, "EVE-777")
    expected = kit.events(sid)
    got = collect(env, after=0, session_id=sid, n=len(expected))
    assert [m["event"] for m in got] == [e["type"] for e in expected]
    assert [int(m["id"]) for m in got] == [e["seq"] for e in expected]
    assert json.loads(got[-1]["data"])["data"]["outcome"] == "BLOCK"


def test_stream_delivers_new_events_live(gate: TestClient, env: Env) -> None:
    kit = GateKit(gate)
    sid, tok = kit.start()
    kit.tool(sid, tok, "list_inbox")
    start = kit.events(sid)[-1]["seq"]

    def emit_later() -> None:
        conn = db.connect(env.gate_db)
        try:
            with db.transaction(conn):
                events.emit(conn, "suspicious_input", sid, {"path": "/proposals", "fields": ["trusted"]}, "2026-10-17T09:00:00Z")
                events.emit(conn, "suspicious_input", sid, {"path": "/proposals", "fields": ["source"]}, "2026-10-17T09:00:01Z")
        finally:
            conn.close()

    kit.tool(sid, tok, "get_vendor", vendor_id="acme")  # gives the stream one event to open on
    got = collect(env, after=start, session_id=sid, n=4, during=emit_later)
    assert [m["event"] for m in got][-2:] == ["suspicious_input", "suspicious_input"]


def test_stream_without_session_filter_includes_everything(gate: TestClient, env: Env) -> None:
    kit = GateKit(gate)
    s1, t1 = kit.start()
    s2, t2 = kit.start()
    kit.tool(s1, t1, "list_inbox")
    kit.tool(s2, t2, "list_inbox")
    total = len(kit.events(s1)) + len(kit.events(s2))
    sessions = {json.loads(m["data"])["session_id"] for m in collect(env, after=0, n=total)}
    assert sessions == {s1, s2}


def test_stream_resumes_after_a_given_event(gate: TestClient, env: Env) -> None:
    kit = GateKit(gate)
    sid, tok = kit.start()
    kit.investigate(sid, tok)
    all_events = kit.events(sid)
    got = collect(env, after=all_events[2]["seq"], session_id=sid, n=1)
    assert int(got[0]["id"]) == all_events[3]["seq"]


def test_step_up_event_says_approval_is_pending(gate: TestClient) -> None:
    kit = GateKit(gate)
    sid, tok = kit.start("step_up", invoice="INV-1052")
    kit.investigate(sid, tok, emails=(), invoice="INV-1052")
    kit.propose(sid, tok, "ACME-4410-2291", amount=520000, invoice="INV-1052")
    decision = [e for e in kit.events(sid) if e["type"] == "decision"][-1]
    assert (decision["data"]["outcome"], decision["data"]["approval"]) == ("STEP_UP", "pending")
