"""Server-Sent Events für Scan- und Job-Fortschritt (R-3): 1×/s, nur bei Änderung."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .sources import scan_status

router = APIRouter(prefix="/api", tags=["events"])

_job_snapshot = None  # wird von api.jobs registriert


def register_job_snapshot(fn) -> None:
    global _job_snapshot
    _job_snapshot = fn


@router.get("/events")
async def events(request: Request):
    async def stream():
        last: dict[str, str] = {}
        yield "retry: 3000\n\n"
        ticks = 0
        while not await request.is_disconnected():
            payloads = {"scan": await asyncio.to_thread(scan_status)}
            if _job_snapshot:
                payloads["jobs"] = await asyncio.to_thread(_job_snapshot)
            for name, data in payloads.items():
                body = json.dumps(data, default=str)
                if name == "scan":
                    # "now" ändert sich jede Sekunde – für Diff ignorieren
                    cmp = json.dumps({k: v for k, v in data.items() if k != "now"}, default=str)
                else:
                    cmp = body
                if last.get(name) != cmp:
                    last[name] = cmp
                    yield f"event: {name}\ndata: {body}\n\n"
            ticks += 1
            if ticks % 15 == 0:
                yield ": ping\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
