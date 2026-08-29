---
id: ROADMAP-001
status: in_progress
created: 2026-08-29
updated: 2026-08-29
---

# ROADMAP-001 — Selected node context for a local AI assistant

## Goal

Let a user select one node in ComfyUI and ask a connected AI
assistant: “How should I configure the selected node?”. The answer stays in
the assistant's own UI. `ComfyUI-AIAssistant` only exposes the current canvas
context over localhost.

## Product boundary

The extension is a read-only context provider, not a chat client and not an
execution tool.

```text
ComfyUI canvas selection (per browser tab)
        ↓
ComfyUI-AIAssistant frontend snapshot
        ↓ same-origin WebSocket into a page registry, memory only
ComfyUI GET /ai-assistant/context
        ↓ localhost pull per turn, or MCP adapter (ROADMAP-002)
any consumer: local assistant, agent, script
        ↓
consumer response
```

### In scope

- one selected node's identity, title and type;
- bounded current widget values;
- input/output slot descriptions and immediate connections;
- current visible graph/subgraph identity when available;
- capture time and monotonically increasing revision;
- multiple selection as count plus bounded node names only, without ids,
  parameters, widgets or links;
- explicit empty-selection and stale/unavailable states;
- RAM-only storage in the ComfyUI process;
- a versioned localhost JSON contract.

### Non-goals

- a consumer or assistant URL setting in the extension;
- a prompt box, chat history, streamed response or answer rendering in ComfyUI;
- graph/widget mutation, workflow execution or queue control;
- MCP integration;
- persistence or telemetry;
- full-workflow transfer by default;
- screenshots or image understanding.

## Context contract v1

The public read route is `GET /ai-assistant/context`. It always returns a
bounded JSON object with `schema_version`, availability/freshness metadata,
workflow metadata and a `selection` array. Empty selection is a valid available
snapshot, distinct from “the frontend has never published a snapshot”. Responses
must carry `Cache-Control: no-store`.

The frontend updates the in-process snapshot through a same-origin WebSocket
into a bounded page registry (owner decision 2026-08-29); the accepted
`POST /ai-assistant/context` route remains as an anonymous write channel for
scripts and debugging. Both change only the extension's volatile mailbox. They
never change the ComfyUI graph or persist content.

Widget values are data, not trusted instructions. Values must be JSON-safe and
bounded before they enter the mailbox. Secret-like fields and oversized strings
must not be exposed.

## Phases

### P0 — Backend mailbox and versioned routes

- Register read/write routes through the existing ComfyUI `PromptServer`.
- Validate shape and request size.
- Store only the latest snapshot in memory.
- Return a deterministic unavailable response before the first frontend update.
- Add isolated backend contract tests.

Acceptance: tests cover initial GET, accepted replacement, invalid JSON/shape,
oversized payload and no-store headers; no node classes or persistence exist.

### P1 — Frontend sync over WebSocket with a page registry

Owner decision 2026-08-29: the frontend↔server channel is a same-origin
WebSocket with a page registry, not POST-with-lease. Rationale: socket
liveness is the page-liveness signal (no heartbeat timeouts, immune to
background-tab timer throttling), multiple browser tabs are first-class
instead of rejected, and the socket is the natural server→page channel for
any future controlled-action roadmap.

- Each browser tab opens `WS /ai-assistant/ws` and sends JSON text frames:
  `register` (page_id), `snapshot` (the same normalized snapshot object the
  POST route accepts), `activate` (on focus/visibilitychange).
- The server keeps a bounded in-memory page registry: page_id, workflow
  identity, last snapshot, connected flag. Socket close marks the page
  disconnected immediately.
- The active page is the most recently activated connected page; its snapshot
  is what the read route serves. When the active page disconnects, the most
  recently activated remaining connected page takes over.
- The public envelope gains additive fields only: `pages` (bounded list of
  page summaries) and `active_page`. `schema_version` stays `/1`; existing
  consumers ignore unknown fields; the MCP tool passes the envelope through
  unchanged (ROADMAP-002).
- The accepted `POST /ai-assistant/context` route stays byte-for-byte as it
  is: an anonymous snapshot channel for scripts and debugging that does not
  create registry pages.
- The frontend extension polls the canvas locally, publishes only when the
  normalized snapshot changes, reconnects with capped backoff, never logs
  payloads, and sends no telemetry.

Acceptance: selecting a node changes GET output; editing a visible widget
increments the revision; deselecting produces an available empty selection;
closing the tab flips `active_page.connected` without a timeout; a second
tab registers and takes over on focus.

### P2 — Consumer access

- Keep the read route as the public integration surface for any consumer: a
  local assistant, agent or script polls `GET /ai-assistant/context` per
  question and injects a compact labelled context block.
- MCP clients integrate through the adapter in ROADMAP-002 instead.
- Degrade cleanly when ComfyUI or the extension is unavailable or stale.

Acceptance: a consumer that fetches the route before answering “How should I
configure the selected node?” receives the live selected node, and a defined
unavailable state when ComfyUI is down.

### P3 — Portable install and live smoke test

- Install the repository into `E:\ComfyUI\ComfyUI\custom_nodes\ComfyUI-AIAssistant`.
- Start the existing portable ComfyUI without changing its Python environment.
- Verify frontend load, selection updates, subgraph behavior and bounded JSON.
- Record compatibility with the installed ComfyUI/frontend versions.

### Deferred — embedded chat and controlled actions

An embedded prompt box would make the extension a second assistant client and
would require assistant address configuration, pairing, session ownership,
streaming, cancellation and response rendering. Consider it only after the
context-provider path proves useful. Controlled workflow actions remain a
separate roadmap with explicit review and confirmation.

## Risks

- ComfyUI frontend selection APIs evolve; prefer supported extension hooks and
  narrow compatibility checks over core-method hijacking.
- Custom widgets may contain non-JSON values or secrets; normalization and
  redaction are part of the security boundary.
- Node ids are scoped by graph/subgraph and are not durable identity.
- A stale snapshot can mislead the model; capture time and graph identity must
  remain visible to the consumer.
- The WebSocket channel adds reconnect and presence state on both sides; keep
  the message set minimal and the public envelope additive so consumers never
  depend on socket lifecycle.
