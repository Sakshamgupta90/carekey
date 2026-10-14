"""HTTP API and screens. Run with: uv run uvicorn carekey.app:create_app --factory"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings, load_settings
from .models import CheckIn, NewVisit, Question
from .ring.webhook import SIGNATURE_HEADER, sign, verify_signature
from .service import CareKey, DemoClock

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
DEMO_KEY = "carekey-demo-signing-key"


class DemoEvent(BaseModel):
    # doorbell | person | package | door_open | door_close
    kind: str = Field(pattern="^(doorbell|person|package|door_open|door_close)$")


class Advance(BaseModel):
    minutes: int = Field(ge=-1440, le=1440)


def create_app(settings: Settings | None = None, service: CareKey | None = None) -> FastAPI:
    settings = settings or load_settings()
    if service is not None:
        ck = service
        clock = service.now if isinstance(service.now, DemoClock) else None
    else:
        clock = DemoClock()
        ck = CareKey(settings, now_fn=clock)
    signing_key = settings.ring_hmac_key or (DEMO_KEY if settings.ring_mode == "fake" else "")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ck.bus.bind(asyncio.get_running_loop())
        tasks = [asyncio.create_task(_every(30, ck.tick))]
        if settings.ring_poll_seconds > 0:
            tasks.append(asyncio.create_task(_every(settings.ring_poll_seconds, ck.poll_history)))
        yield
        for task in tasks:
            task.cancel()

    app = FastAPI(title="CareKey", lifespan=lifespan)
    app.state.carekey = ck

    # -- Ring webhook ----------------------------------------------------------

    @app.post("/webhooks/ring")
    async def ring_webhook(request: Request, background: BackgroundTasks):
        if not signing_key:
            raise HTTPException(500, "RING_HMAC_KEY is not configured.")
        raw = await request.body()
        if not verify_signature(raw, request.headers.get(SIGNATURE_HEADER), signing_key):
            raise HTTPException(401, "Invalid signature.")
        # Ring wants a 200 within 5 seconds; snapshots and Bedrock run afterwards.
        background.add_task(ck.handle_webhook_body, raw)
        return {"ok": True}

    # -- state and live updates -----------------------------------------------

    @app.get("/api/state")
    def state():
        return ck.state()

    @app.get("/api/stream")
    async def stream(request: Request):
        queue = ck.bus.subscribe()

        async def events():
            try:
                yield "retry: 2000\n\n"
                while not await request.is_disconnected():
                    try:
                        data = await asyncio.wait_for(queue.get(), timeout=15)
                        yield f"data: {data}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
            finally:
                ck.bus.unsubscribe(queue)

        return StreamingResponse(events(), media_type="text/event-stream")

    # -- visits and access ----------------------------------------------------

    @app.post("/api/visits")
    def create_visit(body: NewVisit):
        try:
            visit, code = ck.create_visit(body)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"visit": visit.model_dump(mode="json"), "code": code}

    @app.post("/api/checkin")
    def check_in(body: CheckIn):
        return ck.check_in(body.code).model_dump(mode="json")

    @app.post("/api/visits/{visit_id}/checkout")
    def check_out(visit_id: str):
        visit = ck.check_out(visit_id)
        if not visit:
            raise HTTPException(404, "No active visit with that ID.")
        return visit.model_dump(mode="json")

    # -- parent ---------------------------------------------------------------

    @app.post("/api/parent/ok")
    def parent_ok():
        ck.parent_ok()
        return {"ok": True}

    @app.post("/api/packages/{event_id}/collected")
    def package_collected(event_id: str):
        ck.package_collected(event_id)
        return {"ok": True}

    @app.post("/api/ask")
    def ask(body: Question):
        return {"answer": ck.ask(body.question)}

    @app.post("/api/tick")
    def tick():
        return [a.model_dump(mode="json") for a in ck.tick()]

    # -- demo controls (simulated Ring events, time travel) -------------------

    @app.post("/api/demo/event")
    def demo_event(body: DemoEvent):
        _require_demo(settings)
        ring_type, sub_type = {
            "doorbell": ("button_press", None),
            "person": ("motion_detected", "human"),
            "package": ("motion_detected", "package_delivery"),
            "door_open": ("contact_sensor_faulted", None),
            "door_close": ("contact_sensor_cleared", None),
        }[body.kind]
        now = ck.now()
        ms = int(now.timestamp() * 1000)
        device = settings.ring_front_door_device_id
        attrs = {"source": device, "source_type": "devices", "timestamp": ms}
        if sub_type:
            attrs["sub_type"] = sub_type
        payload = {
            "meta": {"version": "1.1", "time": now.isoformat(), "request_id": uuid.uuid4().hex},
            "data": {"id": f"{device}_{ring_type}_{ms}", "type": ring_type, "attributes": attrs},
        }
        raw = json.dumps(payload).encode()
        # Same verification path as a real Ring webhook.
        if not verify_signature(raw, sign(raw, signing_key), signing_key):
            raise HTTPException(500, "Signing failed.")
        event = ck.handle_webhook_body(raw)
        return {"event": event.model_dump(mode="json") if event else None}

    @app.post("/api/demo/advance")
    def demo_advance(body: Advance):
        _require_demo(settings)
        if clock is None:
            raise HTTPException(400, "This app's clock can't be moved.")
        clock.offset_seconds += body.minutes * 60
        alerts = ck.tick()
        return {"now": ck.now().isoformat(), "alerts": [a.model_dump(mode="json") for a in alerts]}

    # -- screens --------------------------------------------------------------

    @app.get("/")
    def index():
        return RedirectResponse("/family.html")

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR), name="web")

    return app


def _require_demo(settings: Settings) -> None:
    if not settings.demo_enabled:
        raise HTTPException(404, "Demo controls are disabled.")


async def _every(seconds: int, fn) -> None:
    while True:
        await asyncio.sleep(seconds)
        try:
            await asyncio.to_thread(fn)
        except Exception:
            log.exception("Background task %s failed", getattr(fn, "__name__", fn))
