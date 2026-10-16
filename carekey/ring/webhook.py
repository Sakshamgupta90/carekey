"""Ring webhook verification and parsing.

From the Ring API reference: webhooks carry an ``X-Signature`` header of the form
``sha256=<hex>``, an HMAC-SHA256 of the raw request body using the partner signing
key. The body is a JSON:API envelope with ``meta`` (version, time, request_id,
account_id) and ``data`` (id, type, attributes, relationships). Ring expects a 200
within 5 seconds and recommends deduplicating on ``meta.request_id``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone

from ..models import DoorEvent, EventKind

SIGNATURE_HEADER = "X-Signature"


def sign(raw_body: bytes, key: str) -> str:
    digest = hmac.new(key.encode(), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(raw_body: bytes, header_value: str | None, key: str) -> bool:
    if not key or not header_value:
        return False
    return hmac.compare_digest(sign(raw_body, key), header_value.strip())


# Ring event type -> our event kind.
_KIND_BY_TYPE = {
    "motion_detected": EventKind.MOTION,
    "motion": EventKind.MOTION,
    "button_press": EventKind.BUTTON_PRESS,
    "ding": EventKind.BUTTON_PRESS,
    "on_demand": EventKind.LIVE_VIEW,
    "contact_sensor_faulted": EventKind.DOOR_OPENED,
    "contact_sensor_cleared": EventKind.DOOR_CLOSED,
}


def kind_for(event_type: str | None) -> EventKind:
    if not event_type:
        return EventKind.OTHER
    base = event_type.split(".", 1)[0]
    return _KIND_BY_TYPE.get(event_type, _KIND_BY_TYPE.get(base, EventKind.OTHER))


def _ts_from_ms(value) -> datetime:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def parse_webhook(raw_body: bytes) -> tuple[str, DoorEvent | None]:
    """Parse a webhook body into (request_id, DoorEvent or None for non-door events)."""
    payload = json.loads(raw_body)
    meta = payload.get("meta") or {}
    data = payload.get("data") or {}
    attrs = data.get("attributes") or {}

    # The event type sits on data.type; fall back to attributes for safety.
    event_type = data.get("type") or attrs.get("event_type")
    kind = kind_for(event_type)
    request_id = str(meta.get("request_id") or data.get("id") or "")
    if kind is EventKind.OTHER:
        return request_id, None

    device_id = attrs.get("source") or _relationship_id(data, "source") or ""
    sub_type = attrs.get("sub_type")
    if not sub_type and event_type and "." in event_type:
        sub_type = event_type.split(".", 1)[1]
    event = DoorEvent(
        id=str(data.get("id") or request_id),
        device_id=device_id,
        kind=kind,
        sub_type=sub_type,
        ts=_ts_from_ms(attrs.get("timestamp")),
    )
    return request_id, event


def parse_history_item(item: dict) -> DoorEvent | None:
    """Convert one ``GET /v1/history/devices/{id}/events`` item into a DoorEvent."""
    attrs = item.get("attributes") or {}
    event_type = attrs.get("event_type")
    kind = kind_for(event_type)
    if kind is EventKind.OTHER:
        return None
    sub_type = event_type.split(".", 1)[1] if event_type and "." in event_type else None
    return DoorEvent(
        id=str(item.get("id")),
        device_id=_relationship_id(item, "source") or "",
        kind=kind,
        sub_type=sub_type,
        ts=_ts_from_ms(attrs.get("start")),
    )


def _relationship_id(obj: dict, name: str) -> str | None:
    rel = (obj.get("relationships") or {}).get(name) or {}
    data = rel.get("data") or {}
    return data.get("id")
