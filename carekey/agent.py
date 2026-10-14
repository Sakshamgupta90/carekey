"""Answers spoken questions from the parent ("Is my parcel still outside?").

Two modes share the same facts:
  - "rules":   offline, deterministic answers (used for tests and as a fallback)
  - "bedrock": a Strands agent on Amazon Bedrock that calls the same facts as tools
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .config import Settings
from .models import EventKind, Severity
from .store import Store
from .timefmt import ago, clock

log = logging.getLogger(__name__)

AGENT_PROMPT = """You are CareKey, a calm, kind helper for an older person living alone who may \
have low vision. You answer questions about their front door, parcels, visitors and today's \
care visits. Use the tools to get facts; never guess. Answer in one or two short spoken \
sentences with plain words and clock times. Never identify or guess who a stranger is. \
If something sounds unsafe, say the door stays locked and that family has been told."""


class Facts:
    """Read-only views over the store, shared by both answer modes."""

    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store

    def parcel_status(self, now: datetime) -> str:
        events = sorted(self.store.list_events(since=now - timedelta(days=1)), key=lambda e: e.ts)
        parcels = [e for e in events if e.sub_type == "package_delivery"]
        if not parcels:
            return "No parcels have been delivered today."
        last = parcels[-1]
        when = f"at {clock(last.ts, self.settings.tz)}, {ago(now, last.ts)}"
        collected = self.store.get_kv(f"package_collected:{last.id}") or any(
            e.kind is EventKind.DOOR_OPENED and e.ts > last.ts for e in events
        )
        if collected:
            return f"A parcel was delivered {when}, and it has been brought in."
        return f"Yes. A parcel was left at the door {when}. It looks like it's still outside."

    def last_visitor(self, now: datetime) -> str:
        door = self.settings.ring_front_door_device_id
        events = [
            e
            for e in self.store.list_events(since=now - timedelta(days=1))
            if e.device_id == door and e.kind in (EventKind.MOTION, EventKind.BUTTON_PRESS)
        ]
        if not events:
            return "No one has come to the door today."
        last = events[0]  # newest first
        desc = (last.description or "Someone was at the door.").rstrip(".")
        return f"At {clock(last.ts, self.settings.tz)}, {ago(now, last.ts)}: {desc}."

    def visits_today(self, now: datetime) -> str:
        tz = self.settings.tz
        today = now.astimezone(tz).date()
        visits = [v for v in self.store.list_visits() if v.start.astimezone(tz).date() == today]
        if not visits:
            return "There are no visits scheduled today."
        parts = []
        for v in visits:
            status = v.status(now)
            who = f"{v.role} {v.visitor_name}"
            if status == "in_progress":
                parts.append(f"{who} is here now, since {clock(v.checked_in_at, tz)}")
            elif status == "completed":
                parts.append(f"{who} came and left at {clock(v.checked_out_at, tz)}")
            elif status == "late":
                parts.append(f"{who} was due at {clock(v.start, tz)} and hasn't arrived yet")
            elif status == "missed":
                parts.append(f"{who} didn't come; they were due at {clock(v.start, tz)}")
            else:
                parts.append(f"{who} is due at {clock(v.start, tz)}")
        return ". ".join(p[0].upper() + p[1:] for p in parts) + "."

    def recent_alerts(self, now: datetime) -> str:
        since = now - timedelta(hours=12)
        alerts = [
            t
            for t in self.store.list_timeline(limit=50)
            if t.kind == "alert" and t.ts >= since and t.severity is not Severity.INFO
        ]
        if not alerts:
            return "Nothing unusual today."
        return " ".join(a.text for a in alerts[:3])


class Answerer:
    def __init__(self, settings: Settings, store: Store, now_fn) -> None:
        self.settings = settings
        self.facts = Facts(settings, store)
        self.now_fn = now_fn
        self._agent_factory = None
        if settings.agent_mode == "bedrock":
            self._agent_factory = self._build_strands_factory()

    def answer(self, question: str) -> str:
        if self._agent_factory:
            try:
                return str(self._agent_factory()(question)).strip()
            except Exception:  # model or network failure: still answer the parent
                log.exception("Strands agent failed; falling back to rules")
        return self.rules_answer(question)

    def rules_answer(self, question: str) -> str:
        q = question.lower()
        now = self.now_fn()
        if any(w in q for w in ("parcel", "package", "delivery", "box")):
            return self.facts.parcel_status(now)
        if any(w in q for w in ("nurse", "carer", "caregiver", "cleaner", "visit", "coming", "appointment")):
            return self.facts.visits_today(now)
        if any(w in q for w in ("who", "door", "knock", "visitor", "someone", "bell")):
            return self.facts.last_visitor(now)
        if any(w in q for w in ("unusual", "wrong", "safe", "alert", "worried")):
            return self.facts.recent_alerts(now)
        return f"{self.facts.visits_today(now)} {self.facts.parcel_status(now)}"

    def _build_strands_factory(self):
        from strands import Agent, tool
        from strands.models import BedrockModel

        facts, now_fn, s = self.facts, self.now_fn, self.settings

        @tool
        def parcel_status() -> str:
            """Whether a parcel was delivered today and whether it is still outside."""
            return facts.parcel_status(now_fn())

        @tool
        def last_visitor() -> str:
            """The most recent person or movement at the front door, with time and description."""
            return facts.last_visitor(now_fn())

        @tool
        def visits_today() -> str:
            """Today's scheduled carer, nurse or cleaner visits and whether each has arrived."""
            return facts.visits_today(now_fn())

        @tool
        def recent_alerts() -> str:
            """Anything unusual today: late visits, lingering strangers, a quiet morning."""
            return facts.recent_alerts(now_fn())

        model = BedrockModel(model_id=s.bedrock_agent_model_id, region_name=s.aws_region)

        def factory():
            return Agent(
                model=model,
                tools=[parcel_status, last_visitor, visits_today, recent_alerts],
                system_prompt=AGENT_PROMPT,
                callback_handler=None,
            )

        return factory
