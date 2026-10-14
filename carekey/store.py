"""SQLite persistence. Small enough for a single home; swap for DynamoDB in the cloud."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime

from .models import DoorEvent, Severity, TimelineEntry, Visit

SCHEMA = """
CREATE TABLE IF NOT EXISTS visits (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    code_used INTEGER NOT NULL DEFAULT 0,
    start_ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS timeline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    text TEXT NOT NULL,
    ref TEXT,
    dedupe_key TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS failed_checkins (
    ts TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str = ":memory:") -> None:
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)

    # -- visits ---------------------------------------------------------------

    def add_visit(self, visit: Visit, code_hash: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO visits (id, data, code_hash, start_ts) VALUES (?, ?, ?, ?)",
                (visit.id, visit.model_dump_json(), code_hash, visit.start.isoformat()),
            )

    def save_visit(self, visit: Visit) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE visits SET data = ? WHERE id = ?", (visit.model_dump_json(), visit.id)
            )

    def get_visit(self, visit_id: str) -> Visit | None:
        row = self._one("SELECT data FROM visits WHERE id = ?", (visit_id,))
        return Visit.model_validate_json(row["data"]) if row else None

    def list_visits(self) -> list[Visit]:
        rows = self._all("SELECT data FROM visits ORDER BY start_ts")
        return [Visit.model_validate_json(r["data"]) for r in rows]

    def visits_with_codes(self) -> list[tuple[Visit, str, bool]]:
        rows = self._all("SELECT data, code_hash, code_used FROM visits ORDER BY start_ts")
        return [
            (Visit.model_validate_json(r["data"]), r["code_hash"], bool(r["code_used"]))
            for r in rows
        ]

    def mark_code_used(self, visit_id: str) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE visits SET code_used = 1 WHERE id = ?", (visit_id,))

    # -- failed check-in attempts (brute-force protection) --------------------

    def record_failed_checkin(self, ts: datetime) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT INTO failed_checkins (ts) VALUES (?)", (ts.isoformat(),))

    def failed_checkins_since(self, since: datetime) -> int:
        row = self._one(
            "SELECT COUNT(*) AS n FROM failed_checkins WHERE ts >= ?", (since.isoformat(),)
        )
        return int(row["n"])

    # -- events ---------------------------------------------------------------

    def add_event(self, event: DoorEvent) -> bool:
        """Store an event. Returns False if it was already stored (idempotent)."""
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO events (id, data, ts) VALUES (?, ?, ?)",
                (event.id, event.model_dump_json(), event.ts.isoformat()),
            )
            return cur.rowcount == 1

    def save_event(self, event: DoorEvent) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE events SET data = ? WHERE id = ?", (event.model_dump_json(), event.id)
            )

    def list_events(self, since: datetime | None = None, limit: int = 200) -> list[DoorEvent]:
        if since:
            rows = self._all(
                "SELECT data FROM events WHERE ts >= ? ORDER BY ts DESC LIMIT ?",
                (since.isoformat(), limit),
            )
        else:
            rows = self._all("SELECT data FROM events ORDER BY ts DESC LIMIT ?", (limit,))
        return [DoorEvent.model_validate_json(r["data"]) for r in rows]

    # -- timeline -------------------------------------------------------------

    def add_timeline(
        self, entry: TimelineEntry, dedupe_key: str | None = None
    ) -> TimelineEntry | None:
        """Append to the family timeline. Returns None if dedupe_key was already used."""
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO timeline (ts, kind, severity, text, ref, dedupe_key) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    entry.ts.isoformat(),
                    entry.kind,
                    entry.severity.value,
                    entry.text,
                    entry.ref,
                    dedupe_key,
                ),
            )
            if cur.rowcount == 0:
                return None
            return entry.model_copy(update={"id": cur.lastrowid})

    def list_timeline(self, limit: int = 100) -> list[TimelineEntry]:
        rows = self._all(
            "SELECT id, ts, kind, severity, text, ref FROM timeline ORDER BY ts DESC, id DESC "
            "LIMIT ?",
            (limit,),
        )
        return [
            TimelineEntry(
                id=r["id"],
                ts=datetime.fromisoformat(r["ts"]),
                kind=r["kind"],
                severity=Severity(r["severity"]),
                text=r["text"],
                ref=r["ref"],
            )
            for r in rows
        ]

    # -- key/value state ------------------------------------------------------

    def get_kv(self, key: str, default=None):
        row = self._one("SELECT value FROM kv WHERE key = ?", (key,))
        return json.loads(row["value"]) if row else default

    def set_kv(self, key: str, value) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO kv (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )

    # -- helpers --------------------------------------------------------------

    def _one(self, sql: str, params: tuple = ()):
        with self._lock:
            return self._db.execute(sql, params).fetchone()

    def _all(self, sql: str, params: tuple = ()):
        with self._lock:
            return self._db.execute(sql, params).fetchall()
