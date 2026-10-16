# Friction log

Problems we hit building CareKey on the Ring Partner API, written as they happened (October 2026).

Format: task · steps · expected vs actual · severity (low / medium / high) · workaround · suggestion.

---

### 1. Playground simulations create live-view events only

- **Task:** Trigger a doorbell press or motion event from the Playground to test an event-driven app.
- **Steps:** Playground → "Simulate live view event" → Package (and Motion).
- **Expected vs actual:** Expected a `motion` (or `ding`) event in Event History, or a webhook. Got only an `on_demand` history event with no detection subtype and an empty `cv_detections` relationship. No webhook can be registered for the Playground device.
- **Severity:** High for event-driven apps: `motion_detected` / `button_press` handling can't be tested end to end without a physical device.
- **Workaround:** Treat `on_demand` events as scenes: download a frame 5 s into the event and classify it with a vision model (parcel → package event, person → motion event, empty porch → ignored).
- **Suggestion:** Let the Playground fire synthetic `motion_detected` (with `sub_type`) and `button_press` events into Event History and to a registered webhook URL.

### 2. Snapshot download returns an undocumented 303 redirect

- **Task:** Download a frame from the Playground device for scene recognition.
- **Steps:** `POST /v1/devices/{id}/media/image/download` with `{"type": "at_timestamp", "timestamp": <ms>}`.
- **Expected vs actual:** The reference documents the request body but not the response. Expected image bytes; got `HTTP 303` with an empty body and a `Location` on a different host (`download-ap-northeast-1.prod.phoenix.devices.amazon.dev`). Following it returned the JPEG, or `416 MEDIA_NOT_FOUND` when nothing was recorded at that time.
- **Severity:** Medium. An HTTP client that doesn't follow redirects silently gets nothing; one that follows them with default settings may forward the bearer token to another host.
- **Workaround:** Follow the redirect with a separate client that sends no token; treat 416 as "no image".
- **Suggestion:** Document the 303 + download-host flow, whether the token must be dropped, and the 416 body, with an example.

### 3. Playground environment isn't described in the API reference

- **Task:** Point the app at the Playground.
- **Steps:** Searched the API reference for a sandbox or staging base URL.
- **Expected vs actual:** Only the production base URL is listed, and the chime section says staging hosts differ without giving them. By trial, Playground tokens work against the production base `https://api.amazonvision.com`. Tokens are read-only (`ava.v1:read`), so write endpoints such as chime playback can't be tried.
- **Severity:** Medium.
- **Workaround:** Used the production base URL with the Playground token.
- **Suggestion:** One table of environments: base URL, token source, scopes, and what each can do.

### 4. Ring documentation MCP server tool names differ from its docs

- **Task:** Query Ring's documentation MCP server (`https://knowledge.appstore-mcp.ring.amazon.dev/mcp`) for Playground details.
- **Steps:** Called `search_docs`, as named on the Ring MCP documentation page.
- **Expected vs actual:** Got `Unknown tool: search_docs`. `tools/list` shows `ring___search_docs` and `ring___get_doc`. Searches for "Playground" returned no Playground content.
- **Severity:** Low.
- **Workaround:** Listed tools first and used the prefixed names.
- **Suggestion:** Update the tool names on the docs page, and index the Playground guide.

### 5. Same event, different names in webhooks and Event History

- **Task:** Handle events from both webhooks and history polling with one code path.
- **Steps:** Compared the Notifications and Event History sections.
- **Expected vs actual:** A doorbell press is `button_press` in webhooks but `ding` in history; motion is `motion_detected` vs `motion` / `motion.<subtype>`; live views (`on_demand`) appear only in history. There's no mapping table in one place.
- **Severity:** Low.
- **Workaround:** A mapping table in our parser (`carekey/ring/webhook.py`).
- **Suggestion:** Add a cross-reference table of event names to both sections.

### 6. Webhook signature has no worked example

- **Task:** Implement `X-Signature` verification.
- **Steps:** Read the Notifications section of the API reference.
- **Expected vs actual:** The algorithm is stated (HMAC-SHA256 over raw body bytes, hex, `sha256=` prefix), but there's no worked example (body, key, expected header) to test an implementation against.
- **Severity:** Low.
- **Workaround:** Wrote our own round-trip tests.
- **Suggestion:** Add a test vector to the docs.

### 7. Amazon Bedrock unusable on a new account

- **Task:** Describe one Ring snapshot with Amazon Bedrock (Converse API).
- **Steps:** Called `converse` with Claude Sonnet 4.5, then Amazon Nova 2 Lite, in us-east-1.
- **Expected vs actual:** Expected a description. Both returned `ThrottlingException: Too many tokens per day` on the first call of the session; Claude Haiku 5.5 returned `AccessDeniedException` (not available for this account).
- **Severity:** High (blocked the AI step entirely).
- **Workaround:** Made the vision step pluggable and used a vision model through Ollama instead; Bedrock remains supported in code.
- **Suggestion:** Show the daily token quota and its reset time next to each model in the Bedrock console, and give new hackathon accounts a usable default.
