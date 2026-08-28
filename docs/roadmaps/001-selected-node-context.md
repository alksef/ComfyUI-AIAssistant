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
ComfyUI canvas selection
        ↓
ComfyUI-AIAssistant frontend snapshot
        ↓ same-origin, memory only
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

The frontend updates the in-process snapshot through a same-origin write route.
That write changes only the extension's volatile mailbox. It never changes the
ComfyUI graph or persists content.

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

### P1 — Frontend selected-node snapshot

- Load as a standard ComfyUI JavaScript extension.
- Observe selection and relevant widget/connection changes without modifying
  core frontend code.
- Publish only when the normalized snapshot changes.
- Handle empty selection, one detailed node, multiple selection as names only,
  and the current visible subgraph.
- Bound/redact values before the same-origin POST.
- Show a small passive indication of which selection is exposed if the current
  frontend API supports it cleanly.

Acceptance: selecting a node changes GET output; editing a visible widget
increments the revision; deselecting produces an available empty selection.

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
