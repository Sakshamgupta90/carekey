# Friction log

Submitted with the hackathon entry (up to 10% judging bonus). One entry per problem, written when it happens.

Format: task · steps · expected vs actual · severity (low / medium / high) · workaround · suggestion.

Entries 1–3 are drafts from reading the API reference. Confirm each against the docs before submitting.

---

### 1. Webhook signature details split across sections

- **Task:** Implement `X-Signature` verification.
- **Steps:** Read the Notifications section of the API reference.
- **Expected vs actual:** Expected one example with a payload, a key and the resulting signature. The algorithm (HMAC-SHA256 over raw body bytes, hex, `sha256=` prefix) is stated, but there's no worked example to test against.
- **Severity:** Low.
- **Workaround:** Wrote our own round-trip tests.
- **Suggestion:** Add a test vector (body, key, expected header) to the docs.

### 2. Image snapshot response shape not shown

- **Task:** Fetch a snapshot to send to Amazon Bedrock.
- **Steps:** Read the Image Snapshots section for `POST /v1/devices/{id}/media/image/download`.
- **Expected vs actual:** The request body is documented (`type: at_timestamp`, `timestamp`, `components`), but we couldn't find whether the response is image bytes or JSON with a download URL.
- **Severity:** Medium.
- **Workaround:** Client handles both.
- **Suggestion:** Show the response headers and body in the reference.

### 3. Playground vs production base URL

- **Task:** Point the app at the Playground.
- **Steps:** Searched the API reference for a sandbox or staging base URL.
- **Expected vs actual:** Only the production URL is listed; the chime section mentions staging hosts differ but doesn't give them.
- **Severity:** Medium.
- **Workaround:** _To fill in during the Playground test._
- **Suggestion:** List each environment's base URL in one table.

<!-- Add entries below as they happen: Playground, Bedrock, Strands, AgentCore, Fire TV / Vega. -->

### 4. Snapshot download returns an undocumented 303 redirect

- **Task:** Download a snapshot from the Playground device to send to Amazon Bedrock.
- **Steps:** `POST /v1/devices/{id}/media/image/download` with `{"type": "at_timestamp", "timestamp": <ms>}`.
- **Expected vs actual:** Expected image bytes. Got `HTTP 303` with an empty body and a `Location` on a different host (`download-ap-northeast-1.prod.phoenix.devices.amazon.dev`). Following it returned `416 MEDIA_NOT_FOUND` because nothing had been recorded at that time.
- **Severity:** Medium (an HTTP client that doesn't follow redirects silently gets nothing).
- **Workaround:** Follow the redirect manually, without forwarding the bearer token to the download host; treat 416 as "no image".
- **Suggestion:** Document the 303 + download-host flow and the 416 response in the Image Snapshots section, with an example.

### 5. Playground simulations create live-view events only

- **Task:** Trigger a doorbell press or motion event from the Playground to test an event-driven app.
- **Steps:** Playground → "Simulate live view event" → Package (also tried earlier: Motion).
- **Expected vs actual:** Expected a `motion` (or `ding`) event in Event History, or a webhook. Got only an `on_demand` history event with no detection subtype and empty `cv_detections`. Snapshots from that time window do work (watermarked JPEG via the 303 download flow).
- **Severity:** High for event-driven apps: there's no way to test `motion_detected` / `button_press` handling without a physical device.
- **Workaround:** Treat `on_demand` events as scenes: fetch a frame 5 s in and classify it with Amazon Bedrock (parcel → package event, person → motion event).
- **Suggestion:** Let the Playground fire synthetic `motion_detected` (with `sub_type`) and `button_press` events into Event History and to a registered webhook URL.

### 6. Amazon Bedrock daily token quota on a new account

- **Task:** Describe one Ring snapshot with Amazon Bedrock (Converse API).
- **Steps:** Called `converse` with Claude Sonnet 4.5, then Amazon Nova 2 Lite, in us-east-1.
- **Expected vs actual:** Expected a description. Both returned `ThrottlingException: Too many tokens per day` on the first call of the session; Claude Haiku 5.5 returned `AccessDeniedException` (not available for this account).
- **Severity:** High (blocks the AI step entirely for the day).
- **Workaround:** App falls back to offline descriptions; requested a quota increase.
- **Suggestion:** Show the daily token quota and its reset time in the Bedrock console next to each model, and give new hackathon accounts a usable default.
