"""Check what the Ring API (or a Playground token) actually returns.

Usage:
    uv run python scripts/check_ring.py [device_id]

Prints Ring's raw responses for devices, capabilities, event history and a snapshot,
and saves each one under samples/ring-check/ for inspection.
Your token is never printed or saved.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from carekey.config import load_settings  # noqa: E402
from carekey.ring.client import LiveRingClient, RingError  # noqa: E402
from carekey.ring.webhook import parse_history_item  # noqa: E402

OUT = Path("samples/ring-check")


def save(name: str, resp) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    content_type = resp.headers.get("Content-Type", "")
    if content_type.startswith("image/"):
        ext = "png" if "png" in content_type else "jpg"
        (OUT / f"{name}.{ext}").write_bytes(resp.content)
    else:
        (OUT / f"{name}.txt").write_text(
            f"HTTP {resp.status_code}\nContent-Type: {content_type}\n\n{resp.text}"
        )


def show(label: str, resp, limit: int = 1500) -> None:
    content_type = resp.headers.get("Content-Type", "")
    print(f"   HTTP {resp.status_code}  Content-Type: {content_type or '(none)'}")
    if content_type.startswith("image/"):
        print(f"   Image, {len(resp.content)} bytes")
        return
    body = resp.text.strip()
    try:
        body = json.dumps(resp.json(), indent=2)
    except ValueError:
        pass
    print("   " + (body[:limit] + ("\n   ... (truncated, full copy saved)" if len(body) > limit else "")).replace("\n", "\n   "))


def call(ring: LiveRingClient, method: str, path: str, **kwargs):
    # Bypass error raising so we can see every status code Ring returns.
    return ring._http.request(method, path, **kwargs)


def main() -> int:
    s = load_settings()
    try:
        ring = LiveRingClient(s.ring_base_url, s.ring_access_token)
    except RingError as exc:
        print(exc)
        return 1

    print("1. Devices  GET /v1/devices")
    resp = call(ring, "GET", "/v1/devices")
    save("1-devices", resp)
    if resp.status_code != 200:
        show("devices", resp)
        return 1
    devices = resp.json().get("data", [])
    for d in devices:
        print(f"   - {d.get('id')}  {d.get('attributes', {}).get('name')}")
    if not devices:
        print("   No devices on this account.")
        return 1
    device_id = sys.argv[1] if len(sys.argv) > 1 else devices[0]["id"]

    print("\n2. Capabilities  GET /v1/devices/{id}/capabilities")
    resp = call(ring, "GET", f"/v1/devices/{device_id}/capabilities")
    save("2-capabilities", resp)
    show("capabilities", resp, limit=1200)

    print("\n3. Event history  GET /v1/history/devices/{id}/events")
    resp = call(ring, "GET", f"/v1/history/devices/{device_id}/events")
    save("3-history", resp)
    show("history", resp)
    items = resp.json().get("data", []) if resp.status_code == 200 else []
    parsed = [e for e in (parse_history_item(i) for i in items) if e]
    print(f"   {len(items)} raw items, {len(parsed)} understood as door events")
    unknown = sorted({(i.get('attributes') or {}).get('event_type') for i in items} - {None})
    if unknown:
        print(f"   event_type values seen: {', '.join(map(str, unknown))}")

    print("\n4. Snapshot  POST /v1/devices/{id}/media/image/download")
    # Ask for the moment of the newest event if there is one, else a few seconds ago.
    at_ms = int(time.time() * 1000) - 5000
    if items:
        start = (items[0].get("attributes") or {}).get("start")
        if start:
            at_ms = int(start)
    resp = call(
        ring,
        "POST",
        f"/v1/devices/{device_id}/media/image/download",
        json={"type": "at_timestamp", "timestamp": at_ms},
    )
    save("4-snapshot", resp)
    show("snapshot", resp)

    print(f"\nRaw responses saved in {OUT}/ (no token inside).")
    print(f"Set RING_FRONT_DOOR_DEVICE_ID={json.dumps(device_id)} in .env to use this device.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
