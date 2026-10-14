"""Care checks: things a caring family member would notice, including what DIDN'T happen.

Each check is deterministic and deduplicated, so running it every minute is safe.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from .config import Settings
from .models import EventKind, Severity, TimelineEntry
from .store import Store
from .timefmt import clock

LINGER_LOOKBACK = timedelta(minutes=15)
PACKAGE_WAIT = timedelta(minutes=60)
OVERSTAY = timedelta(minutes=30)


class CareMonitor:
    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store

    def run(self, now: datetime) -> list[TimelineEntry]:
        """Run every check; return only alerts that are new."""
        alerts: list[TimelineEntry] = []
        for check in (
            self._late_or_missed_visits,
            self._overstays,
            self._lingering,
            self._packages_waiting,
            self._quiet_morning,
        ):
            for entry, key in check(now):
                saved = self.store.add_timeline(entry, dedupe_key=key)
                if saved:
                    alerts.append(saved)
        return alerts

    # -- checks ---------------------------------------------------------------

    def _late_or_missed_visits(self, now: datetime):
        tz = self.settings.tz
        late = timedelta(minutes=self.settings.late_after_minutes)
        for visit in self.store.list_visits():
            if visit.checked_in_at:
                continue
            who = f"{visit.role.capitalize()} {visit.visitor_name}"
            if now > visit.end:
                yield (
                    _alert(now, Severity.CRITICAL, f"{who} missed the visit due at {clock(visit.start, tz)}.", visit.id),
                    f"missed:{visit.id}",
                )
            elif now > visit.start + late:
                minutes = int((now - visit.start).total_seconds() // 60)
                yield (
                    _alert(now, Severity.WARNING, f"{who} is {minutes} minutes late and hasn't arrived.", visit.id),
                    f"late:{visit.id}",
                )

    def _overstays(self, now: datetime):
        for visit in self.store.list_visits():
            if visit.checked_in_at and not visit.checked_out_at and now > visit.end + OVERSTAY:
                who = f"{visit.role.capitalize()} {visit.visitor_name}"
                yield (
                    _alert(now, Severity.WARNING, f"{who} hasn't checked out, 30 minutes after the visit ended.", visit.id),
                    f"overstay:{visit.id}",
                )

    def _lingering(self, now: datetime):
        """Someone seen repeatedly at the door for several minutes without ringing."""
        door = self.settings.ring_front_door_device_id
        events = [
            e
            for e in self.store.list_events(since=now - LINGER_LOOKBACK)
            if e.device_id == door and e.ts <= now
        ]
        people = sorted(
            (e for e in events if e.kind is EventKind.MOTION and e.sub_type in ("human", None)),
            key=lambda e: e.ts,
        )
        if len(people) < 2:
            return
        first, last = people[0], people[-1]
        span = last.ts - first.ts
        if span < timedelta(minutes=self.settings.linger_minutes):
            return
        rang = any(e.kind is EventKind.BUTTON_PRESS and first.ts <= e.ts <= last.ts for e in events)
        if rang or self._expected_visit_near(first.ts):
            return
        minutes = int(span.total_seconds() // 60)
        yield (
            _alert(
                now,
                Severity.WARNING,
                f"Someone has been at the door for {minutes} minutes without ringing. The door stays locked.",
                first.id,
            ),
            f"linger:{first.id}",
        )

    def _packages_waiting(self, now: datetime):
        events = sorted(self.store.list_events(since=now - timedelta(days=1)), key=lambda e: e.ts)
        for event in events:
            if event.sub_type != "package_delivery" or now - event.ts < PACKAGE_WAIT:
                continue
            if self.store.get_kv(f"package_collected:{event.id}"):
                continue
            opened_after = any(e.kind is EventKind.DOOR_OPENED and e.ts > event.ts for e in events)
            if opened_after:
                continue
            yield (
                _alert(
                    now,
                    Severity.INFO,
                    f"A parcel delivered at {clock(event.ts, self.settings.tz)} is still outside.",
                    event.id,
                ),
                f"package:{event.id}",
            )

    def _quiet_morning(self, now: datetime):
        """No sign of the parent being up and about by the usual time."""
        tz = self.settings.tz
        local = now.astimezone(tz)
        hh, mm = (int(x) for x in self.settings.quiet_morning_by.split(":"))
        if local.time() < time(hh, mm):
            return
        midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
        today = midnight.date().isoformat()
        last_ok = self.store.get_kv("parent_checkin")
        if last_ok and datetime.fromisoformat(last_ok) >= midnight:
            return
        door_used = any(
            e.kind in (EventKind.DOOR_OPENED, EventKind.DOOR_CLOSED)
            for e in self.store.list_events(since=midnight)
        )
        if door_used:
            return
        yield (
            _alert(
                now,
                Severity.WARNING,
                f"No front door activity and no check-in from "
                f"{self.settings.parent_name} by {self.settings.quiet_morning_by}.",
                None,
            ),
            f"quiet:{today}",
        )

    def _expected_visit_near(self, ts: datetime) -> bool:
        grace = timedelta(minutes=self.settings.checkin_early_minutes)
        return any(v.start - grace <= ts <= v.end for v in self.store.list_visits())


def _alert(now: datetime, severity: Severity, text: str, ref: str | None) -> TimelineEntry:
    return TimelineEntry(ts=now, kind="alert", severity=severity, text=text, ref=ref)
