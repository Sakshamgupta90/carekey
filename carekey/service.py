"""Wires Ring events, scene description, access control and care checks together."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .access import AccessService, SimulatedLock
from .agent import Answerer
from .bus import EventBus
from .care import CareMonitor
from .config import Settings
from .models import AccessDecision, DoorEvent, EventKind, NewVisit, Severity, TimelineEntry, Visit
from .ring.client import FakeRingClient, LiveRingClient, RingClient
from .ring.webhook import parse_webhook
from .store import Store
from .timefmt import clock, utcnow
from .vision import BedrockDescriber, Describer, FakeDescriber

log = logging.getLogger(__name__)

_SEVERITY_BY_URGENCY = {"urgent": Severity.CRITICAL, "attention": Severity.WARNING}
LIVE_VIEW_FRAME_OFFSET_MS = 5000
# What a live-view frame shows -> the door event it stands for.
_LIVE_VIEW_AS = {
    "package": (EventKind.MOTION, "package_delivery"),
    "delivery": (EventKind.MOTION, "human"),
    "visitor": (EventKind.MOTION, "human"),
    "carer": (EventKind.MOTION, "human"),
}


def _classify_live_view(event: DoorEvent) -> DoorEvent:
    """Ring live views (e.g. Playground simulations) carry no detection type, so the
    scene description decides: a parcel becomes a package event, a person a motion
    event. Anything else stays a plain live view and raises no alerts."""
    kind_sub = _LIVE_VIEW_AS.get(event.category or "")
    if not kind_sub:
        return event
    kind, sub_type = kind_sub
    return event.model_copy(update={"kind": kind, "sub_type": sub_type})


class CareKey:
    def __init__(
        self,
        settings: Settings,
        store: Store | None = None,
        ring: RingClient | None = None,
        describer: Describer | None = None,
        now_fn=utcnow,
    ) -> None:
        self.settings = settings
        self.now = now_fn
        self.store = store or Store(settings.db_path)
        self.ring = ring or self._make_ring(settings)
        self.describer = describer or self._make_describer(settings)
        self.lock = SimulatedLock()
        self.access = AccessService(settings, self.store, self.lock)
        self.monitor = CareMonitor(settings, self.store)
        self.answerer = Answerer(settings, self.store, now_fn)
        self.bus = EventBus()

    @staticmethod
    def _make_ring(s: Settings) -> RingClient:
        if s.ring_mode == "live":
            return LiveRingClient(s.ring_base_url, s.ring_access_token)
        return FakeRingClient(s.ring_front_door_device_id)

    @staticmethod
    def _make_describer(s: Settings) -> Describer:
        if s.vision_mode == "bedrock":
            return BedrockDescriber(s.bedrock_vision_model_id, s.aws_region)
        return FakeDescriber()

    # -- Ring events ----------------------------------------------------------

    def handle_webhook_body(self, raw_body: bytes) -> DoorEvent | None:
        _, event = parse_webhook(raw_body)
        return self.handle_event(event) if event else None

    def handle_event(self, event: DoorEvent) -> DoorEvent | None:
        """Describe, store and broadcast one Ring event. Duplicates are ignored."""
        if not self.store.add_event(event):
            return None
        image = None
        if event.kind in (EventKind.MOTION, EventKind.BUTTON_PRESS, EventKind.LIVE_VIEW):
            # A live view's first frames can be black while the stream starts.
            offset_ms = LIVE_VIEW_FRAME_OFFSET_MS if event.kind is EventKind.LIVE_VIEW else 0
            try:
                image = self.ring.snapshot(
                    event.device_id, int(event.ts.timestamp() * 1000) + offset_ms
                )
            except Exception:
                log.exception("Snapshot failed for %s", event.id)
        try:
            scene = self.describer.describe(event, image)
        except Exception:
            log.exception("Scene description failed for %s", event.id)
            scene = FakeDescriber().describe(event, None)
        event = event.model_copy(update=scene)
        if event.kind is EventKind.LIVE_VIEW:
            event = _classify_live_view(event)
        self.store.save_event(event)

        entry = self.store.add_timeline(
            TimelineEntry(
                ts=event.ts,
                kind="event",
                severity=_SEVERITY_BY_URGENCY.get(event.urgency or "", Severity.INFO),
                text=event.description or "Activity at the front door.",
                ref=event.id,
            )
        )
        self.bus.publish({"type": "door_event", "event": event.model_dump(mode="json")})
        if entry:
            self.bus.publish({"type": "timeline", "entry": entry.model_dump(mode="json")})
        self.tick()
        return event

    def poll_history(self) -> int:
        """Fetch recent front-door events from Ring Event History. Returns how many were new."""
        new = 0
        for event in self.ring.history(self.settings.ring_front_door_device_id):
            if self.handle_event(event):
                new += 1
        return new

    # -- care checks ----------------------------------------------------------

    def tick(self) -> list[TimelineEntry]:
        alerts = self.monitor.run(self.now())
        for alert in alerts:
            self.bus.publish({"type": "timeline", "entry": alert.model_dump(mode="json")})
        return alerts

    # -- visits and access ----------------------------------------------------

    def create_visit(self, new: NewVisit) -> tuple[Visit, str]:
        visit, code = self.access.create_visit(new)
        tz = self.settings.tz
        self._log(
            "visit",
            Severity.INFO,
            f"Visit booked: {visit.role} {visit.visitor_name}, "
            f"{clock(visit.start, tz)} to {clock(visit.end, tz)}.",
            visit.id,
        )
        return visit, code

    def check_in(self, code: str) -> AccessDecision:
        now = self.now()
        decision = self.access.check_in(code, now)
        if decision.granted:
            visit = self.store.get_visit(decision.visit_id)
            self._log(
                "access",
                Severity.INFO,
                f"{visit.role.capitalize()} {visit.visitor_name} arrived at {clock(now, self.settings.tz)}. "
                f"Door unlocked for {self.settings.unlock_seconds // 60} minutes.",
                visit.id,
            )
            self.bus.publish(
                {"type": "access", "granted": True, "visitor": f"{visit.role} {visit.visitor_name}"}
            )
        else:
            self._log("access", Severity.WARNING, f"Check-in refused: {decision.reason}", decision.visit_id)
            self.bus.publish({"type": "access", "granted": False, "reason": decision.reason})
        return decision

    def check_out(self, visit_id: str) -> Visit | None:
        visit = self.access.check_out(visit_id, self.now())
        if visit:
            self._log(
                "access",
                Severity.INFO,
                f"{visit.role.capitalize()} {visit.visitor_name} left at "
                f"{clock(visit.checked_out_at, self.settings.tz)}. Door locked.",
                visit.id,
            )
        return visit

    # -- parent actions -------------------------------------------------------

    def parent_ok(self) -> None:
        now = self.now()
        self.store.set_kv("parent_checkin", now.isoformat())
        self._log("checkin", Severity.INFO, f"{self.settings.parent_name} checked in: all fine.", None)

    def package_collected(self, event_id: str) -> None:
        self.store.set_kv(f"package_collected:{event_id}", True)
        self._log("event", Severity.INFO, "Parcel brought inside.", event_id)

    def ask(self, question: str) -> str:
        return self.answerer.answer(question)

    # -- views ----------------------------------------------------------------

    def state(self) -> dict:
        now = self.now()
        late = timedelta(minutes=self.settings.late_after_minutes)
        return {
            "now": now.isoformat(),
            "timezone": self.settings.timezone_name,
            "parent_name": self.settings.parent_name,
            "family_name": self.settings.family_name,
            "ring_mode": self.settings.ring_mode,
            "demo_enabled": self.settings.demo_enabled,
            "lock": {
                "unlocked": self.lock.is_unlocked(now),
                "unlocked_until": self.lock.unlocked_until.isoformat() if self.lock.is_unlocked(now) else None,
            },
            "visits": [
                {**v.model_dump(mode="json"), "status": v.status(now, late)}
                for v in self.store.list_visits()
            ],
            "events": [e.model_dump(mode="json") for e in self.store.list_events(limit=20)],
            "timeline": [t.model_dump(mode="json") for t in self.store.list_timeline(limit=50)],
        }

    def _log(self, kind: str, severity: Severity, text: str, ref: str | None) -> None:
        entry = self.store.add_timeline(TimelineEntry(ts=self.now(), kind=kind, severity=severity, text=text, ref=ref))
        if entry:
            self.bus.publish({"type": "timeline", "entry": entry.model_dump(mode="json")})


class DemoClock:
    """Real time plus an offset, so a demo can jump ahead to show a late visit."""

    def __init__(self) -> None:
        self.offset_seconds = 0.0

    def __call__(self) -> datetime:
        return utcnow() + timedelta(seconds=self.offset_seconds)