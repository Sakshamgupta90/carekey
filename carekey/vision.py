"""Scene description: what is happening at the door, never who someone is."""

from __future__ import annotations

import json
import re
from typing import Protocol

from .models import DoorEvent, EventKind

SYSTEM_PROMPT = """You describe a single frame from a home doorbell camera for an older person \
with low vision and their family.

Rules:
- Describe actions, objects, clothing and context only. NEVER identify, name or guess who \
anyone is, and never comment on age, race, gender or appearance beyond clothing.
- One short plain sentence, under 20 words, e.g. "A courier in a high-vis vest is holding a parcel."
- If the image is unclear, say so plainly.

Reply with JSON only:
{"description": "...", "category": "delivery|visitor|carer|package|vehicle|nobody|unknown", \
"urgency": "routine|attention|urgent"}"""


class Describer(Protocol):
    def describe(self, event: DoorEvent, image: bytes | None) -> dict: ...


class FakeDescriber:
    """Deterministic descriptions from the Ring event type, for offline use and tests."""

    def describe(self, event: DoorEvent, image: bytes | None) -> dict:
        if event.kind is EventKind.BUTTON_PRESS:
            return {
                "description": "Someone pressed the doorbell.",
                "category": "visitor",
                "urgency": "attention",
            }
        if event.sub_type == "package_delivery":
            return {
                "description": "A parcel has been left at the front door.",
                "category": "package",
                "urgency": "routine",
            }
        if event.sub_type == "human":
            return {
                "description": "A person is standing at the front door.",
                "category": "visitor",
                "urgency": "attention",
            }
        if event.kind is EventKind.LIVE_VIEW:
            return {
                "description": "The front door camera was checked.",
                "category": "unknown",
                "urgency": "routine",
            }
        if event.kind is EventKind.DOOR_OPENED:
            return {"description": "The front door was opened.", "category": "unknown", "urgency": "routine"}
        if event.kind is EventKind.DOOR_CLOSED:
            return {"description": "The front door was closed.", "category": "unknown", "urgency": "routine"}
        return {"description": "Movement near the front door.", "category": "unknown", "urgency": "routine"}


class BedrockDescriber:
    """Sends the Ring snapshot to a vision model on Amazon Bedrock (Converse API)."""

    def __init__(self, model_id: str, region: str) -> None:
        import boto3

        self._client = boto3.client("bedrock-runtime", region_name=region)
        self._model_id = model_id
        self._fallback = FakeDescriber()

    def describe(self, event: DoorEvent, image: bytes | None) -> dict:
        if not image:
            return self._fallback.describe(event, image)
        fmt = "png" if image[:8] == b"\x89PNG\r\n\x1a\n" else "jpeg"
        resp = self._client.converse(
            modelId=self._model_id,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"image": {"format": fmt, "source": {"bytes": image}}},
                        {"text": f"Ring event: {event.kind.value} ({event.sub_type or 'none'})."},
                    ],
                }
            ],
            inferenceConfig={"maxTokens": 200, "temperature": 0},
        )
        text = "".join(
            block.get("text", "") for block in resp["output"]["message"]["content"]
        )
        return parse_description(text) or self._fallback.describe(event, image)


OLLAMA_PROMPT = """This is a frame from a home doorbell camera. In one short plain sentence, \
say what is at the front door: mention any parcel or package, any person, and any vehicle. \
Ignore the text and logos overlaid on the image. Never identify or guess who anyone is."""

_NOBODY = re.compile(r"\b(no one|nobody|empty|unoccupied)\b")
# A negation covers the rest of its clause: "no parcels, people, or vehicles are visible".
_NEGATED = re.compile(r"\b(no|not|without|nobody|no one|neither|nor)\b[^.;:]*")
_PACKAGE = re.compile(r"\b(parcels?|packages?|boxes|box|cardboard|deliver(y|ed))\b")
_PERSON = re.compile(
    r"\b(person|people|man|woman|men|women|someone|somebody|courier|driver|visitor|child|boy|girl)\b"
)
_VEHICLE = re.compile(r"\b(car|cars|van|truck|vehicle|motorbike|motorcycle|bike)\b")


def categorize(text: str) -> tuple[str, str]:
    """(category, urgency) from a free-text scene description.

    Small local models don't follow JSON instructions reliably, so the category comes
    from the words they use. Errs on the side of "unknown" rather than inventing one.
    """
    t = text.lower()
    positive = _NEGATED.sub(" ", t)  # only what is said to be there
    person = bool(_PERSON.search(positive))
    package = bool(_PACKAGE.search(positive))
    if person and package:
        return "delivery", "attention"
    if person:
        return "visitor", "attention"
    if package:
        return "package", "routine"
    if _VEHICLE.search(positive):
        return "vehicle", "routine"
    if positive != t or _NOBODY.search(t):
        return "nobody", "routine"
    return "unknown", "routine"


class OllamaDescriber:
    """Describes Ring snapshots with a vision model served by Ollama.

    With a local model the footage never leaves the home computer.
    """

    def __init__(self, model: str, base_url: str = "http://localhost:11434", timeout: float = 180.0) -> None:
        import httpx

        self._http = httpx.Client(base_url=base_url, timeout=timeout)
        self._model = model
        self._fallback = FakeDescriber()

    def describe(self, event: DoorEvent, image: bytes | None) -> dict:
        if not image:
            return self._fallback.describe(event, image)
        import base64

        resp = self._http.post(
            "/api/chat",
            json={
                "model": self._model,
                "stream": False,
                "options": {"temperature": 0},
                "messages": [
                    {
                        "role": "user",
                        "content": OLLAMA_PROMPT,
                        "images": [base64.b64encode(image).decode()],
                    }
                ],
            },
        )
        resp.raise_for_status()
        text = (resp.json().get("message") or {}).get("content", "").strip()
        parsed = parse_description(text)
        if parsed:
            return parsed
        sentence = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0].strip()
        if not sentence:
            return self._fallback.describe(event, image)
        category, urgency = categorize(sentence)
        return {"description": sentence[:200], "category": category, "urgency": urgency}


def parse_description(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not data.get("description"):
        return None
    return {
        "description": str(data["description"])[:200],
        "category": str(data.get("category", "unknown")),
        "urgency": str(data.get("urgency", "routine")),
    }
