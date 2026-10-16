import httpx
import pytest

from carekey.models import DoorEvent, EventKind
from carekey.vision import OllamaDescriber, categorize


@pytest.mark.parametrize(
    "text, category",
    [
        ("A cardboard package sits on the snowy front steps.", "package"),
        ("A courier in a vest is holding a parcel at the door.", "delivery"),
        ("A man is standing at the front door.", "visitor"),
        ("A red car is parked in the driveway.", "vehicle"),
        ("The porch is empty, with no one around.", "nobody"),
        ("There is no package and no one at the door.", "nobody"),
        ("Snow covers the steps.", "unknown"),
        # Real Ollama outputs for Ring Playground frames:
        ("There are no parcels, people, or vehicles at the front door.", "nobody"),
        ("There is a package at the front door, and no people or vehicles are visible.", "package"),
        ("A man without a package is waiting.", "visitor"),
    ],
)
def test_categorize(text, category):
    assert categorize(text)[0] == category


def test_ollama_describer_sends_image_and_classifies(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        seen["model"] = body["model"]
        seen["has_image"] = bool(body["messages"][0]["images"][0])
        return httpx.Response(
            200, json={"message": {"content": "A brown package is on the steps. The yard is snowy."}}
        )

    d = OllamaDescriber("moondream")
    d._http = httpx.Client(base_url="http://ollama.test", transport=httpx.MockTransport(handler))
    event = DoorEvent(id="e", device_id="d", kind=EventKind.LIVE_VIEW, ts="2026-10-16T07:19:22Z")
    result = d.describe(event, b"\xff\xd8\xff-image")
    assert seen == {"model": "moondream", "has_image": True}
    assert result == {
        "description": "A brown package is on the steps.",
        "category": "package",
        "urgency": "routine",
    }
