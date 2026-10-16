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
