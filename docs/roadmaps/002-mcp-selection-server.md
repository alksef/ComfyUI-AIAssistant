---
id: ROADMAP-002
status: in_progress
created: 2026-08-29
updated: 2026-08-29
---

# ROADMAP-002 — In-process MCP endpoint for the selection context

## Goal

Serve a minimal MCP server inside the ComfyUI process as an HTTP endpoint
next to the existing context route, so that any MCP client (OpenCode, Claude
Code, Cursor, others) integrates with one URL and no extra process. The MCP
endpoint is a thin protocol layer over the same mailbox that backs
`GET /ai-assistant/context`; it adds no second source of truth.

## Product boundary

```text
ComfyUI process (aiohttp, already running)
  ├─ GET  /ai-assistant/context        (existing, unchanged)
  └─ POST /mcp                         (new, same process)
        └─ pure JSON-RPC dispatcher → mailbox directly
any MCP client, configured with a URL
```

The MCP surface is served by the ComfyUI process and lives and dies with it.
There is no child process, no separate interpreter and no extra port; the
endpoint rides the ComfyUI port wherever ComfyUI runs.

### In scope

- one read-only tool `get_selection` returning the same envelope as the read
  route, verbatim, with freshness metadata (`captured_at`, `revision`)
  passed through;
- a stateless Streamable HTTP subset: a single `POST /mcp` endpoint that
  accepts one JSON-RPC message per request and answers either a JSON
  response (requests) or `202 Accepted` with an empty body (notifications);
- the minimal method set: `initialize`, `notifications/initialized`,
  `tools/list`, `tools/call`, `ping`; unknown requests get `-32601`,
  malformed payloads `-32700`/`-32600`, unknown notifications are accepted
  silently;
- `GET`/`DELETE` on the endpoint return `405`: no SSE stream, no sessions;
- a pure dispatcher module with no framework imports, fully testable
  offline, so a stdio shell could later reuse it verbatim;
- bounded request bodies, `no-store` responses, no payload logging;
- README install instructions: one URL for OpenCode, Claude Code and
  generic MCP clients.

### Non-goals

- any write surface: no mailbox mutation, no workflow, queue, model or file
  actions through MCP — controlled actions remain a separate future roadmap;
- SSE streaming, server-initiated notifications, `Mcp-Session-Id` sessions
  or request batching;
- an MCP SDK or any new runtime dependency;
- a stdio transport in this roadmap (a later thin shell over the same
  dispatcher remains possible as a separate decision);
- authentication, CORS for browser clients, or any non-localhost exposure
  promise;
- caching: every `tools/call` reads the live mailbox.

## Tool contract

- Name: `get_selection`. Input: empty object.
- Output: `content[0].text` is the context envelope as compact JSON,
  byte-equivalent in content to the read-route body (`schema_version`,
  `available`, `received_at`, `snapshot`). The MCP layer adds nothing and
  rewrites nothing.
- An absent snapshot (`available: false`) is a normal result, not an error;
  the calling model sees the unavailable state and freshness metadata and
  judges staleness itself.
- There is no transport-level unavailability distinct from the envelope:
  the endpoint exists exactly when ComfyUI runs.

## Protocol details (stateless subset)

- `initialize`: echo the client's `protocolVersion` (default `2025-06-18`
  when absent), `capabilities: {tools: {listChanged: false}}`, `serverInfo`
  from module constants.
- `tools/list`: exactly one tool — name, one-line read-only description,
  `inputSchema` `{type: object, properties: {}, additionalProperties:
  false}`.
- `tools/call` result: `{content: [{type: "text", text: <compact JSON>}],
  isError: false}`.
- `ping` → result `{}`.
- Response `id` must round-trip exactly (string, number or null).
- Known methods with invalid `params` get `-32602`.
- A body that is not a single JSON object (arrays, scalars) gets `-32600`.

## Boundary amendments

AGENTS.md boundaries stay as written, with one addition when P0 starts: the
extension serves one more inbound read-only route, `POST /mcp`, on the
ComfyUI port. It never mutates state through it, never logs payloads, and
adds no dependencies. Serving this endpoint is inbound traffic like the
existing context routes; the no-outbound-requests boundary is untouched.

## Phases

### P0 — Dispatcher and endpoint

- Add the pure dispatcher module and the `POST /mcp` route; share envelope
  construction with the read route without changing its bytes.
- Enforce a 64 KiB body limit with declared-plus-actual streaming checks;
  notifications answer `202` with an empty body; `GET`/`DELETE` answer
  `405` with `Allow: POST`; every JSON response carries `no-store`.
- Acceptance: offline tests cover handshake, tool listing, call with
  available and unavailable envelopes, ping, unknown method, malformed and
  oversized bodies, notification `202` and id round-trip; the existing
  context-route tests stay green and unchanged.

### P1 — Live client verification

- Blocked by ROADMAP-001 P3: the plugin must be installed and running in
  the portable ComfyUI first.
- Configure OpenCode (`type: remote` with the endpoint URL) and Claude Code
  (`claude mcp add --transport http`) against the running endpoint and
  record both client logs as evidence.
- Acceptance: both clients answer "what is selected in ComfyUI" from the
  live selection.

### P2 — Publish readiness

- README: URL configuration for OpenCode, Claude Code and generic clients;
  an explicit "read-only, rides the ComfyUI port, reachable wherever
  ComfyUI is reachable" statement.
- Decide the license file with the owner; publish to GitHub as an owner
  action.
- Acceptance: fresh clone plus install plus one URL entry works against a
  default portable ComfyUI without editing the server.

## Risks

- A hand-rolled transport subset can drift from the MCP spec; the
  stateless JSON-only mode is small, the dispatcher is pure and
  exhaustively tested, and P1 verifies two real clients before publishing.
- An endpoint on the ComfyUI port is reachable wherever ComfyUI is
  reachable, including LAN exposure; it exposes exactly the bounded
  selection snapshot the read route already exposes and nothing else —
  document rather than hide.
- Clients that only speak stdio cannot use this endpoint; the shared
  dispatcher keeps a later stdio shell cheap.
- The read route has existing consumers; its response bytes must not
  change — held by regression tests.
