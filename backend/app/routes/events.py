"""GET /sessions/{id}/events (persisted, ordered), GET /events/stream (SSE).

The SSE stream is still the Phase 0 stub (canned events); Phase 4 wires it to app.events.
"""

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app import db, stub_data
from app.deps import ConnDep
from app.models import Event

router = APIRouter(tags=["events"])


@router.get("/sessions/{session_id}/events", response_model=list[Event])
def session_events(session_id: str, conn: ConnDep) -> list[Event]:
    return db.list_events(conn, session_id)


@router.get("/events/stream")
async def event_stream() -> EventSourceResponse:
    async def gen() -> AsyncIterator[dict[str, str]]:
        for e in stub_data.SESSION_EVENTS:
            yield {"event": e.type, "id": str(e.seq), "data": e.model_dump_json()}
            await asyncio.sleep(0.5)
        while True:
            await asyncio.sleep(3600)

    return EventSourceResponse(gen(), ping=15)
