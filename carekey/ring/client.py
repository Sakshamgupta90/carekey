"""Ring API client (live) and an offline fake with the same interface.

Endpoints come from the Ring API reference (base https://api.amazonvision.com):
  GET  /v1/devices
  GET  /v1/history/devices/{device_id}/events
  POST /v1/devices/{device_id}/media/image/download
All calls are server-side with ``Authorization: Bearer <token>``. The API allows
100 requests/second per client and returns 429 with ``Retry-After`` when exceeded.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Protocol

import httpx

from ..models import DoorEvent
from .webhook import parse_history_item


class RingError(RuntimeError):
    pass


class RingClient(Protocol):
    def list_devices(self) -> list[dict]: ...

    def history(self, device_id: str, event_types: str | None = None) -> list[DoorEvent]: ...

    def snapshot(self, device_id: str, at_ms: int) -> bytes | None: ...


class LiveRingClient:
    def __init__(self, base_url: str, access_token: str, timeout: float = 10.0) -> None:
        if not access_token:
            raise RingError("RING_ACCESS_TOKEN is empty. Get a token from the Ring Playground.")
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        delay = 1.0
        for _ in range(4):
            resp = self._http.request(method, path, **kwargs)
            if resp.status_code != 429:
                break
            time.sleep(float(resp.headers.get("Retry-After", delay)))
            delay *= 2
        if resp.status_code == 401:
            raise RingError("Ring rejected the token (401). Playground tokens expire after 30 minutes.")
        if resp.status_code >= 400:
            raise RingError(f"Ring API {method} {path} failed: {resp.status_code} {resp.text[:300]}")
        return resp

    def list_devices(self) -> list[dict]:
        return self._request("GET", "/v1/devices").json().get("data", [])

    def history(self, device_id: str, event_types: str | None = None) -> list[DoorEvent]:
        params = {"event_types": event_types} if event_types else None
        body = self._request("GET", f"/v1/history/devices/{device_id}/events", params=params).json()
        events = [parse_history_item(item) for item in body.get("data", [])]
        return [e for e in events if e is not None]

    def snapshot(self, device_id: str, at_ms: int) -> bytes | None:
        resp = self._request(
            "POST",
            f"/v1/devices/{device_id}/media/image/download",
            json={"type": "at_timestamp", "timestamp": at_ms},
        )
        content_type = resp.headers.get("Content-Type", "")
        if content_type.startswith("image/"):
            return resp.content
        # The reference doesn't show the response shape; if it returns JSON with a
        # download URL instead of bytes, follow it.
        try:
            body = resp.json()
        except ValueError:
            return None
        url = _find_url(body)
        if not url:
            return None
        media = httpx.get(url, timeout=10.0)
        return media.content if media.status_code == 200 else None


def _find_url(obj) -> str | None:
    if isinstance(obj, str) and obj.startswith("https://"):
        return obj
    if isinstance(obj, dict):
        for value in obj.values():
            found = _find_url(value)
            if found:
                return found
    if isinstance(obj, list):
        for value in obj:
            found = _find_url(value)
            if found:
                return found
    return None


class FakeRingClient:
    """Offline stand-in: one front-door doorbell, snapshots from samples/ if present."""

    def __init__(self, device_id: str, samples_dir: str = "samples") -> None:
        self.device_id = device_id
        self._samples = Path(samples_dir)
        self.next_snapshot: str | None = None  # sample filename for the next snapshot

    def list_devices(self) -> list[dict]:
        return [
            {
                "type": "devices",
                "id": self.device_id,
                "attributes": {"name": "Front Door (simulated)"},
            }
        ]

    def history(self, device_id: str, event_types: str | None = None) -> list[DoorEvent]:
        return []

    def snapshot(self, device_id: str, at_ms: int) -> bytes | None:
        if not self.next_snapshot:
            return None
        path = self._samples / self.next_snapshot
        return path.read_bytes() if path.is_file() else None
