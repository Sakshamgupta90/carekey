import json

from carekey.models import EventKind
from carekey.ring.webhook import parse_history_item, parse_webhook, sign, verify_signature

KEY = "test-key"


def body(event_type, **attrs):
    payload = {
        "meta": {"version": "1.1", "time": "2026-10-20T09:00:00Z", "request_id": "req-1", "account_id": "acc"},
        "data": {
            "id": f"dev1_{event_type}_1792486800000",
            "type": event_type,
            "attributes": {"source": "dev1", "source_type": "devices", "timestamp": 1792486800000, **attrs},
        },
    }
    return json.dumps(payload).encode()


def test_signature_round_trip():
    raw = body("button_press")
    header = sign(raw, KEY)
    assert header.startswith("sha256=")
    assert verify_signature(raw, header, KEY)


def test_signature_rejects_tampering_and_missing_values():
    raw = body("button_press")
    header = sign(raw, KEY)
    assert not verify_signature(raw + b" ", header, KEY)
    assert not verify_signature(raw, header, "other-key")
    assert not verify_signature(raw, None, KEY)
    assert not verify_signature(raw, header, "")


def test_parse_motion_with_sub_type():
    request_id, event = parse_webhook(body("motion_detected", sub_type="package_delivery"))
    assert request_id == "req-1"
    assert event.kind is EventKind.MOTION
    assert event.sub_type == "package_delivery"
    assert event.device_id == "dev1"
    assert event.ts.year == 2026


def test_parse_button_press():
    _, event = parse_webhook(body("button_press"))
    assert event.kind is EventKind.BUTTON_PRESS
    assert event.sub_type is None


def test_parse_contact_sensor():
    _, event = parse_webhook(body("contact_sensor_faulted"))
    assert event.kind is EventKind.DOOR_OPENED


def test_non_door_events_are_ignored():
    _, event = parse_webhook(body("device_online"))
    assert event is None


def test_parse_history_item_with_dotted_type():
    item = {
        "type": "history-events",
        "id": "h1",
        "attributes": {"event_type": "motion.human", "start": 1792486800000, "end": 1792486810000},
        "relationships": {"source": {"data": {"type": "devices", "id": "dev1"}}},
    }
    event = parse_history_item(item)
    assert event.kind is EventKind.MOTION
    assert event.sub_type == "human"
    assert event.device_id == "dev1"
