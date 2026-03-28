"""
SSE (Server-Sent Events) live update bus.

NOTE: This in-process asyncio.Queue approach is correct for single-process
uvicorn deployments. With multiple workers (--workers N), each worker has
its own queue — clients miss events from other workers. To fix: swap
_clients for a Redis pub/sub channel (redis is in requirements.txt).
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter()

# Active client queues
_clients: list[asyncio.Queue] = []


async def broadcast(event_type: str, payload: dict) -> None:
    """Push an event to all connected SSE clients."""
    for q in _clients:
        try:
            q.put_nowait({"type": event_type, "data": payload})
        except asyncio.QueueFull:
            pass  # Drop event for a lagging client rather than blocking


async def _event_stream(request: Request):
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _clients.append(q)
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(q.get(), timeout=25.0)
                yield f"event: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    finally:
        if q in _clients:
            _clients.remove(q)


@router.get("/events")
async def event_stream(request: Request):
    """Subscribe to live analysis and graph update events."""
    return StreamingResponse(
        _event_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
