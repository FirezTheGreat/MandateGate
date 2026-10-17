"""GET /sessions/{id}/events (persisted, ordered) and GET /events/stream (SSE, live).

The stream is backed by the events table: every event the gate emits is committed there first,
and the stream polls for seq > last-sent. That survives restarts and reloads, needs no
cross-thread signalling, and lets a dashboard reconnect with Last-Event-ID and miss nothing.

    GET /events/stream                      live from now, all sessions
    GET /events/stream?session_id=ses_…     one session
    GET /events/stream?after=0              replay everything first, then live
    Last-Event-ID: <seq>                    resume after a dropped connection

Each message: `event: <type>`, `id: <seq>`, `data: <Event JSON>`.
"""

import asyncio
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from app import db
from app.deps import ConnDep, SettingsDep
from app.models import Event

router = APIRouter(tags=["events"])
POLL_S = 0.3


@router.get("/sessions/{session_id}/events", response_model=list[Event])
def session_events(session_id: str, conn: ConnDep) -> list[Event]:
    return db.list_events(conn, session_id)


async def event_source(
    connect: Callable[[], sqlite3.Connection], *, after: int, session_id: str | None, poll_s: float,
    is_disconnected: Callable[[], Awaitable[bool]],
) -> AsyncIterator[dict[str, str]]:
    def fetch(last: int) -> list[Event]:
        conn = connect()
        try:
            return db.events_since(conn, last, session_id)
        finally:
            conn.close()

    last = after
    while not await is_disconnected():
        for e in await asyncio.to_thread(fetch, last):
            last = e.seq
            yield {"event": e.type, "id": str(e.seq), "data": e.model_dump_json()}
        await asyncio.sleep(poll_s)


@router.get("/events/stream")
async def event_stream(request: Request, settings: SettingsDep, session_id: str | None = None, after: int | None = None) -> EventSourceResponse:
    resume = request.headers.get("last-event-id", "")
    if after is None:
        if resume.isdigit():
            after = int(resume)
        else:
            conn = db.connect(settings.gate_db_path)
            try:
                after = db.max_event_seq(conn)  # live only
            finally:
                conn.close()
    source = event_source(
        lambda: db.connect(settings.gate_db_path), after=after, session_id=session_id, poll_s=POLL_S,
        is_disconnected=request.is_disconnected,
    )
    return EventSourceResponse(source, ping=15)
