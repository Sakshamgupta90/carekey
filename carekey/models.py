"""Domain models. All datetimes are timezone-aware UTC."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, Field


class EventKind(StrEnum):
    MOTION = "motion"
    BUTTON_PRESS = "button_press"
    DOOR_OPENED = "door_opened"  # contact sensor faulted
    DOOR_CLOSED = "door_closed"  # contact sensor cleared
    OTHER = "other"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class DoorEvent(BaseModel):
    """A normalised Ring event, enriched with a scene description."""

    id: str
    device_id: str
    kind: EventKind
    sub_type: str | None = None  # e.g. "human", "package_delivery"
    ts: datetime
    description: str | None = None
    category: str | None = None  # delivery | visitor | carer | package | unknown
    urgency: str | None = None  # routine | attention | urgent


class Visit(BaseModel):
    """A scheduled visit by a carer, nurse, cleaner or delivery."""

    id: str
    visitor_name: str
    role: str
    start: datetime
    end: datetime
    checked_in_at: datetime | None = None
    checked_out_at: datetime | None = None
    missed_alerted: bool = False

    def status(self, now: datetime, late_after: timedelta = timedelta(minutes=15)) -> str:
        if self.checked_out_at:
            return "completed"
        if self.checked_in_at:
            return "in_progress"
        if now > self.end:
            return "missed"
        if now > self.start + late_after:
            return "late"
        if now >= self.start:
            return "due"
        return "upcoming"


class TimelineEntry(BaseModel):
    id: int | None = None
    ts: datetime
    kind: str  # event | access | alert | checkin | answer
    severity: Severity = Severity.INFO
    text: str
    ref: str | None = None


class AccessDecision(BaseModel):
    granted: bool
    reason: str
    visit_id: str | None = None
    unlocked_until: datetime | None = None


class NewVisit(BaseModel):
    visitor_name: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=40)
    start: datetime
    end: datetime


class CheckIn(BaseModel):
    code: str = Field(min_length=4, max_length=12)


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=500)
