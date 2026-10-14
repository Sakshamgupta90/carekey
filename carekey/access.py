"""Who may come in, and when.

The AI never decides to unlock. The door opens only when ALL of these hold:
  1. a one-time code matches a scheduled visit that hasn't used it yet,
  2. the current time is inside that visit's window (with a small early grace),
  3. Ring has seen someone at the front door in the last few minutes,
  4. there haven't been too many wrong codes recently.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta

from .config import Settings
from .models import AccessDecision, EventKind, NewVisit, Visit
from .store import Store

MAX_FAILED_ATTEMPTS = 5
FAILED_WINDOW = timedelta(minutes=10)


def hash_code(visit_id: str, code: str) -> str:
    return hashlib.sha256(f"{visit_id}:{code}".encode()).hexdigest()


class SimulatedLock:
    """Stands in for a smart lock. Relocks itself after the unlock window."""

    def __init__(self) -> None:
        self.unlocked_until: datetime | None = None

    def unlock(self, now: datetime, seconds: int) -> datetime:
        self.unlocked_until = now + timedelta(seconds=seconds)
        return self.unlocked_until

    def lock(self) -> None:
        self.unlocked_until = None

    def is_unlocked(self, now: datetime) -> bool:
        return self.unlocked_until is not None and now < self.unlocked_until


class AccessService:
    def __init__(self, settings: Settings, store: Store, lock: SimulatedLock) -> None:
        self.settings = settings
        self.store = store
        self.lock = lock

    def create_visit(self, new: NewVisit) -> tuple[Visit, str]:
        if new.end <= new.start:
            raise ValueError("Visit end must be after its start.")
        visit = Visit(
            id=uuid.uuid4().hex[:12],
            visitor_name=new.visitor_name.strip(),
            role=new.role.strip(),
            start=new.start,
            end=new.end,
        )
        code = f"{secrets.randbelow(1_000_000):06d}"
        self.store.add_visit(visit, hash_code(visit.id, code))
        return visit, code

    def check_in(self, code: str, now: datetime) -> AccessDecision:
        s = self.settings
        if self.store.failed_checkins_since(now - FAILED_WINDOW) >= MAX_FAILED_ATTEMPTS:
            return AccessDecision(
                granted=False, reason="Too many wrong codes. Check-in is paused for 10 minutes."
            )

        match: tuple[Visit, bool] | None = None
        for visit, code_hash, used in self.store.visits_with_codes():
            if hmac.compare_digest(code_hash, hash_code(visit.id, code.strip())):
                match = (visit, used)
                break
        if match is None:
            self.store.record_failed_checkin(now)
            return AccessDecision(granted=False, reason="That code isn't valid.")

        visit, used = match
        if used:
            return AccessDecision(
                granted=False, reason="This code has already been used.", visit_id=visit.id
            )
        if now < visit.start - timedelta(minutes=s.checkin_early_minutes):
            return AccessDecision(
                granted=False, reason="It's too early for this visit.", visit_id=visit.id
            )
        if now > visit.end:
            return AccessDecision(
                granted=False, reason="This visit's time window has ended.", visit_id=visit.id
            )
        if not self._someone_at_door(now):
            return AccessDecision(
                granted=False,
                reason="Ring hasn't seen anyone at the door. Ring the doorbell, then try again.",
                visit_id=visit.id,
            )

        self.store.mark_code_used(visit.id)
        visit.checked_in_at = now
        self.store.save_visit(visit)
        until = self.lock.unlock(now, s.unlock_seconds)
        return AccessDecision(
            granted=True, reason="Door unlocked.", visit_id=visit.id, unlocked_until=until
        )

    def check_out(self, visit_id: str, now: datetime) -> Visit | None:
        visit = self.store.get_visit(visit_id)
        if not visit or not visit.checked_in_at or visit.checked_out_at:
            return None
        visit.checked_out_at = now
        self.store.save_visit(visit)
        self.lock.lock()
        return visit

    def _someone_at_door(self, now: datetime) -> bool:
        since = now - timedelta(minutes=self.settings.presence_window_minutes)
        door = self.settings.ring_front_door_device_id
        for event in self.store.list_events(since=since):
            if event.device_id != door or event.ts > now:
                continue
            if event.kind is EventKind.BUTTON_PRESS:
                return True
            if event.kind is EventKind.MOTION and event.sub_type in (None, "human"):
                return True
        return False
