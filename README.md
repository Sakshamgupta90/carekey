# CareKey

**Lets the right people into an older person's home, and tells the family when something isn't right. Built on the Ring API.**

Older people living alone get scheduled visits from nurses, carers and cleaners. Today that usually means a key-safe code everyone knows, or a frail person struggling to reach the door, and families find out about a missed visit only afterwards.

CareKey uses Ring to:

- **Let scheduled visitors in safely.** A visitor rings the doorbell and enters a one-time code. The door unlocks only for that visit's time window, and only after Ring has seen someone at the door.
- **Notice what didn't happen.** A nurse 15 minutes late, a missed visit, no front-door activity by 11:00, a parcel left outside for an hour.
- **Keep strangers out.** Someone lingering without ringing never gets the door opened; the parent gets a large on-screen and spoken description, and the family gets a heads-up.
- **Answer questions in plain words.** "Is my parcel still outside?" "Who was at the door?"

CareKey describes **what** is happening, never **who** someone is: no face recognition, and no footage stored.

Ring track entry for the Build, Ship, Shape: Amazon Developer Hackathon (accessibility, care-taking, access control, package management).

## Screens

| Screen | URL | For |
|---|---|---|
| Home | `/home.html` | The parent: large text, spoken alerts, arrow-key (TV remote) and voice friendly |
| Family | `/family.html` | The family: live timeline, alerts, booking visits, demo controls |
| Visitor check-in | `/carer.html` | Carers and nurses: enter the one-time code at the door |

## Quick start (no Ring account needed)

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
git clone https://github.com/Sakshamgupta90/carekey.git && cd carekey
cp .env.example .env
uv sync
uv run pytest
uv run uvicorn carekey.app:create_app --factory --port 8000
```

Open http://localhost:8000/family.html, http://localhost:8000/home.html and http://localhost:8000/carer.html side by side. With the default `RING_MODE=fake`, the **Demo controls** on the family screen send simulated Ring events through the same signed-webhook parsing path as real ones, and **Skip** buttons move the clock forward to show late visits.

Try: book a visit → enter its code on the visitor page (refused, nobody at the door) → **Doorbell pressed** → enter the code again (door unlocks) → **Skip 20 minutes** on a second visit (late alert).

## Run with the Ring API (Ring Playground)

1. Create a free developer account at [developer.ring.com](https://developer.ring.com) and open the **Playground**.
2. Generate an OAuth token (valid 30 minutes) and put it in `.env`:
   ```
   RING_MODE=live
   RING_ACCESS_TOKEN=<token>
   RING_POLL_SECONDS=10
   ```
3. Find your device ID and check the API responds:
   ```bash
   uv run python scripts/check_ring.py
   ```
   Put the printed ID in `.env` as `RING_FRONT_DOOR_DEVICE_ID`.
4. Turn on scene recognition (next section), start the app, then in the Playground use **Simulate live view event → Package**. Within about 20 seconds the parent's screen shows the parcel alert and "Is my parcel outside?" answers yes.

## Scene recognition

Ring's Playground simulations arrive as live-view (`on_demand`) events with real footage but no detection type. CareKey downloads a frame 5 seconds into the event and asks a vision model what is at the door; a parcel becomes a package event, a person a motion event, and an empty porch stays quiet.

| `VISION_MODE` | Uses | Notes |
|---|---|---|
| `fake` (default) | Canned descriptions | Offline; for tests and the built-in demo |
| `ollama` | Any vision model served by [Ollama](https://ollama.com) (`OLLAMA_VISION_MODEL`) | A local model such as `moondream` keeps footage on the computer; `*-cloud` models run on ollama.com |
| `bedrock` | Amazon Bedrock Converse API (`BEDROCK_VISION_MODEL_ID`) | Needs AWS credentials with model access |

The model writes one plain sentence; the category comes from its words, with negated clauses ("no people or vehicles are visible") ignored (`carekey/vision.py`).

## How it works

```
Ring device / Playground ──▶ Event History poll  or  signed webhook
                                        │
                     Ring snapshot (303 → download host) ──▶ vision model
                                        │
                        Event store ──▶ Care checks (every 30 s)
                                        │
            Home screen · Family timeline · Visitor check-in   (live via Server-Sent Events)
```

### Ring API usage (`carekey/ring/`)

Base URL `https://api.amazonvision.com`, bearer token, all calls server-side.

| Use | Endpoint |
|---|---|
| Device discovery | `GET /v1/devices` |
| Events (polling) | `GET /v1/history/devices/{device_id}/events` — `ding`, `motion`, `on_demand` |
| Events (push) | Webhooks `button_press`, `motion_detected` (`sub_type` `human`, `package_delivery`), contact sensors; `X-Signature: sha256=<hex>` HMAC-SHA256 over the raw body, answered within 5 s, deduplicated |
| Frames for scene recognition | `POST /v1/devices/{device_id}/media/image/download` — answers `303`; the image is fetched from the download host **without** the bearer token; `416 MEDIA_NOT_FOUND` means nothing was recorded |

### Safety design: the AI never unlocks the door

The door opens only when **all** of these hold (`carekey/access.py`):

1. the one-time code matches a scheduled visit and hasn't been used,
2. the time is inside that visit's window (15 minutes early grace),
3. Ring saw someone at the front door in the last 5 minutes,
4. there haven't been 5 wrong codes in the last 10 minutes.

The lock relocks itself after 2 minutes. The lock in this repo is simulated: Ring's API doesn't control locks.

### Questions from the parent (`carekey/agent.py`)

Answers come from the event history and visit schedule with deterministic rules, so they work offline. `AGENT_MODE=bedrock` swaps in a Strands agent on Amazon Bedrock that uses the same facts as tools (install with `uv sync --extra agent`).

## Tests

```bash
uv run pytest
```

Covers webhook signatures and parsing, the Ring client against recorded Playground responses (303 snapshot flow, 416, history), access rules, every care check, scene categorisation from real model output, and the HTTP API.

## Project layout

```
carekey/
  app.py        HTTP API, Ring webhook, live stream, demo controls
  service.py    wires everything together; live-view scene classification
  ring/         webhook verification + parsing, Ring API client, offline fake
  vision.py     scene description: Ollama, Amazon Bedrock, or offline
  access.py     one-time codes, time windows, presence check, simulated lock
  care.py       late/missed visits, lingering, parcels, quiet morning
  agent.py      answers questions (rules, or Strands on Bedrock)
web/            home, family and visitor screens (no build step)
tests/          unit and API tests
scripts/        check_ring.py: verifies a Ring token, device, history and snapshot
FRICTION_LOG.md developer-experience notes from building on the Ring API
```

## License

MIT, see [LICENSE](LICENSE).
