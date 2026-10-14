# CareKey

**Lets the right people into an older person's home, and tells the family when something isn't right. Built on Ring.**

Older people living alone get scheduled visits from nurses, carers and cleaners. Today that usually means a key-safe code everyone knows, or a frail person struggling to reach the door, and families find out about a missed visit only afterwards.

CareKey uses Ring events to:

- **Let scheduled visitors in safely.** A visitor rings the doorbell and enters a one-time code. The door unlocks only for that visit's time window, and only after Ring has seen someone at the door.
- **Notice what didn't happen.** A nurse 15 minutes late, a missed visit, no front-door activity by 11:00, a parcel left outside for an hour.
- **Keep strangers out.** Someone lingering without ringing never gets the door opened; the parent gets a clear spoken and on-screen description and the family gets a heads-up.
- **Answer questions in plain words.** "Is my parcel still outside?" "Who was at the door?"

CareKey describes **what** is happening, never **who** someone is. No face recognition, and no footage stored.

## Screens

| Screen | URL | For |
|---|---|---|
| Home | `/home.html` | The parent: large text, spoken alerts, D-pad and voice friendly (TV-ready) |
| Family | `/family.html` | The family: live timeline, alerts, booking visits, demo controls |
| Visitor check-in | `/carer.html` | Carers and nurses: enter the one-time code at the door |

## Run it

Requires [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env
uv sync
uv run uvicorn carekey.app:create_app --factory --port 8000
```

Open http://localhost:8000/family.html, http://localhost:8000/home.html and http://localhost:8000/carer.html side by side. With the default `RING_MODE=fake`, the demo controls on the family screen send simulated Ring events through the same signed webhook path as real ones.

Run the tests:

```bash
uv run pytest
```

## How it works

```
Ring doorbell / Playground ──webhook (HMAC-verified)──▶ CareKey API
                                                          │
                     Ring snapshot ──▶ Amazon Bedrock (scene, never identity)
                                                          │
                                       Event store ──▶ Care checks (every 30 s)
                                                          │
                       Home screen · Family timeline · Visitor check-in (live via SSE)
```

### Ring integration (`carekey/ring/`)

Built against the Ring (Amazon Vision) API reference, base `https://api.amazonvision.com`:

| Use | Endpoint |
|---|---|
| Receive events | Webhooks, `X-Signature: sha256=<hex>` HMAC-SHA256 over the raw body, answered within 5 s, deduplicated |
| Fallback when webhooks can't reach us | `GET /v1/history/devices/{device_id}/events` (set `RING_POLL_SECONDS`) |
| Snapshot for scene description | `POST /v1/devices/{device_id}/media/image/download` |
| Device discovery | `GET /v1/devices` |

Events used: `button_press`, `motion_detected` (sub-types `human`, `package_delivery`), and contact sensor `contact_sensor_faulted` / `contact_sensor_cleared`.

To try a real Ring token (for example from the Ring Playground):

```bash
RING_ACCESS_TOKEN=... uv run python scripts/ring_spike.py
```

### AWS integration

| Service | Use | Code |
|---|---|---|
| Amazon Bedrock (Converse API, vision) | Turns each Ring snapshot into a one-sentence scene description with category and urgency | `carekey/vision.py` |
| Strands Agents SDK on Bedrock | Answers the parent's questions using tools over the event history and visit schedule | `carekey/agent.py` |

Enable with `VISION_MODE=bedrock` and `AGENT_MODE=bedrock` (needs AWS credentials with Bedrock model access). Both fall back to offline behaviour if Bedrock is unavailable, so the parent always gets an answer.

### Safety design: the AI never unlocks the door

The door opens only when **all** of these hold (`carekey/access.py`):

1. the one-time code matches a scheduled visit and hasn't been used,
2. the time is inside that visit's window (15 minutes early grace),
3. Ring saw someone at the front door in the last 5 minutes,
4. there haven't been 5 wrong codes in the last 10 minutes.

The lock relocks itself after 2 minutes. The lock in this repo is simulated; Ring's API doesn't control locks.

## Project layout

```
carekey/
  app.py        HTTP API, webhook, live stream, demo controls
  service.py    wires everything together
  ring/         webhook verification + parsing, Ring API client, offline fake
  vision.py     Bedrock scene description
  access.py     one-time codes, time windows, presence check, simulated lock
  care.py       late/missed visits, lingering, parcels, quiet morning
  agent.py      answers questions (rules or Strands on Bedrock)
web/            home, family and visitor screens (no build step)
tests/          unit and API tests
scripts/        Ring API check script
```

## License

MIT, see [LICENSE](LICENSE).
