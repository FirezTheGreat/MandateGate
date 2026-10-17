"""GET /sessions/{id}/events, GET /events/stream (SSE).

STUB: replays canned events, then holds the stream open (sse-starlette sends pings).
The real event bus lands in Phase 4.
"""

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app import stub_data
from app.models import Event

router = APIRouter(tags=["events"])


@router.get("/sessions/{session_id}/events", response_model=list[Event])
def session_events(session_id: str) -> list[Event]:
    return [e.model_copy(update={"session_id": session_id}) for e in stub_data.SESSION_EVENTS]


@router.get("/events/stream")
async def event_stream() -> EventSourceResponse:
    async def gen() -> AsyncIterator[dict[str, str]]:
        for e in stub_data.SESSION_EVENTS:
            yield {"event": e.type, "id": str(e.seq), "data": e.model_dump_json()}
            await asyncio.sleep(0.5)
        while True:
            await asyncio.sleep(3600)

    return EventSourceResponse(gen(), ping=15)
