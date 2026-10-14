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
