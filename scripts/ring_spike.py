"""Check what the Ring API (or Playground token) actually gives us.

Usage:
    RING_ACCESS_TOKEN=... uv run python scripts/ring_spike.py [device_id]

Prints devices, recent event history and whether a snapshot can be fetched, and saves
the snapshot to samples/spike-snapshot.* so it can be sent to Bedrock.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from carekey.config import load_settings  # noqa: E402
from carekey.ring.client import LiveRingClient, RingError  # noqa: E402


def main() -> int:
    s = load_settings()
    try:
        ring = LiveRingClient(s.ring_base_url, s.ring_access_token)
    except RingError as exc:
        print(exc)
        return 1

    print("1. Devices (GET /v1/devices)")
    try:
        devices = ring.list_devices()
    except RingError as exc:
        print("   FAILED:", exc)
        return 1
    for d in devices:
        print(f"   - {d.get('id')}  {d.get('attributes', {}).get('name')}")
    if not devices:
        print("   No devices on this account.")
        return 1

    device_id = sys.argv[1] if len(sys.argv) > 1 else devices[0]["id"]
    print(f"\n2. Event history for {device_id}")
    try:
        events = ring.history(device_id)
        for e in events[:10]:
            print(f"   - {e.ts.isoformat()}  {e.kind.value}  {e.sub_type or ''}")
        print(f"   {len(events)} door events parsed")
    except RingError as exc:
        print("   FAILED:", exc)

    print("\n3. Snapshot (POST /v1/devices/{id}/media/image/download)")
    try:
        image = ring.snapshot(device_id, int(time.time() * 1000))
        if image:
            ext = "png" if image[:4] == b"\x89PNG" else "jpg"
            out = Path("samples") / f"spike-snapshot.{ext}"
            out.parent.mkdir(exist_ok=True)
            out.write_bytes(image)
            print(f"   Saved {len(image)} bytes to {out}")
        else:
            print("   No image returned (response shape may differ; check the raw response).")
    except RingError as exc:
        print("   FAILED:", exc)

    print(f"\nSet RING_FRONT_DOOR_DEVICE_ID={json.dumps(device_id)} in .env to use this device.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
