"""LiveRingClient against recorded Ring Playground behaviour (no network)."""

import httpx

from carekey.ring.client import LiveRingClient

BASE = "https://api.amazonvision.com"
DOWNLOAD = "https://download-ap-northeast-1.prod.phoenix.devices.amazon.dev/v1/download?sig=abc"
JPEG = b"\xff\xd8\xff\xe0fake-jpeg"


def client(handler) -> LiveRingClient:
    return LiveRingClient(BASE, "token-123", transport=httpx.MockTransport(handler))


def test_snapshot_follows_303_without_sending_token():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.amazonvision.com":
            assert request.headers["Authorization"] == "Bearer token-123"
            return httpx.Response(303, headers={"Location": DOWNLOAD})
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, headers={"Content-Type": "image/jpeg"}, content=JPEG)

    assert client(handler).snapshot("dev1", 1792486800000) == JPEG
    assert seen["auth"] is None


def test_snapshot_no_media_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.amazonvision.com":
            return httpx.Response(303, headers={"Location": DOWNLOAD})
        return httpx.Response(
            416,
            json={"errors": [{"status": "416", "code": "MEDIA_NOT_FOUND"}]},
        )

    assert client(handler).snapshot("dev1", 1792486800000) is None


def test_history_parses_events_and_skips_unknown_types():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/history/devices/dev1/events"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "type": "history-events",
                        "id": "e1",
                        "attributes": {"event_type": "motion.package_delivery", "start": 1792486800000},
                        "relationships": {"source": {"data": {"type": "devices", "id": "dev1"}}},
                    },
                    {
                        "type": "history-events",
                        "id": "e2",
                        "attributes": {"event_type": "device_online", "start": 1792486800000},
                    },
                ]
            },
        )

    events = client(handler).history("dev1")
    assert [e.sub_type for e in events] == ["package_delivery"]


def test_history_on_demand_is_a_live_view():
    from carekey.models import EventKind
    from carekey.ring.webhook import parse_history_item

    item = {
        "type": "history-events",
        "id": "lv1",
        "attributes": {"event_type": "on_demand", "start": 1792133618022, "end": 1792133649764},
        "relationships": {"source": {"data": {"type": "devices", "id": "dev1"}}},
    }
    event = parse_history_item(item)
    assert event.kind is EventKind.LIVE_VIEW
