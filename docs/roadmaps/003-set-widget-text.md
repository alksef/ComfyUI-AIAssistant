---
id: ROADMAP-003
status: in_progress
created: 2026-08-29
updated: 2026-08-29
---

# ROADMAP-003 — Controlled text insertion into the selected node

## Goal

Let an agent insert text into a text-like widget of the currently selected
node, reusing the existing WebSocket channel in the server→page direction.
This is the first and only write surface: one widget value of one selected
node, on explicit request, guarded by a revision check.

## Product boundary

```text
agent
  └─ MCP tools/call set_widget_text(widget, text, expected_revision)
       ↓ validate (shape, bounds, selection state, revision CAS)
     outbox (RAM, one command, bounded)
       ↓ WS push to the ACTIVE page socket
     aiAssistant.js applies widget.value = text (undo/dirty behave
       like a manual edit), publishes a fresh snapshot immediately
       (revision + 1)
       ↓ normal context-sync path
     mailbox revision grows → tools/call sees it in a bounded wait
  └─ result: "applied" (with the new revision) or "queued" (page
     offline / no confirmation within the bound)
```

## In scope

- one MCP tool `set_widget_text` with required `widget` (exact widget
  name as `get_selection` reports it), `text`, and `expected_revision`;
- only the currently selected node, only on the active page, only with a
  single selection (`selection_detail: full`);
- only text-like widgets (`type` of `text`, `customtext`, or `string`);
- text bounded to 8,192 characters, widget name to 128;
- revision CAS: the command is refused if the mailbox snapshot's revision
  does not equal `expected_revision`;
- a bounded synchronous confirmation (poll the mailbox up to ~3 s for the
  revision to advance) so the caller usually gets "applied" in one call;
- tool execution failures are MCP results with `isError: true` and a
  human-readable message (protocol-level errors stay JSON-RPC errors).

## Non-goals

- writing combos, numbers, toggles, or any non-text widget;
- creating, deleting, linking nodes; queue execution; workflow files;
  settings; multi-node or multi-page writes;
- confirmation dialogs in ComfyUI (the canvas edit is immediately visible
  and undoable — that is the confirmation);
- any second transport: the WS channel from ROADMAP-001 P1 is the only
  downstream path.

## Tool contract

`set_widget_text` params: `{widget: string, text: string,
expected_revision: int}`. Results:

- success: `{content: [{type: "text", text: "<status json>"},],
  isError: false}` where status json is `{"status": "applied",
  "revision": <new>, "widget": <name>}` (or `"queued"` with the reason);
- refusals (isError: true, static messages): invalid params shape;
  no selection; multiple selection; active page offline; unknown widget
  name; widget not text-like; revision mismatch (message includes the
  current revision so the caller can retry without a second read).

`tools/list` gains the second tool with a matching inputSchema
(required properties, no additional properties).

## Boundary amendment (AGENTS.md)

The read-only boundary gains one explicit, narrow carve-out: at an
agent's explicit MCP request, the plugin writes text into exactly one
text-like widget of the currently selected node on the active page,
guarded by revision CAS and size bounds; the edit behaves on the canvas
like a manual widget edit (undo works, workflow becomes dirty). Nothing
else may mutate: no queue, no graph structure, no settings, no files.

## Phases

### P0 — Pure command validation + dispatcher surface (offline)

- `ai_assistant/commands.py`: shape/bounds validation, selection-state
  resolution against a snapshot, MCP result shaping, command frame
  builder. Stdlib only, no I/O.
- `ai_assistant/mcp_protocol.py`: second tool in `tools/list`; routing to
  an injected command handler (dispatcher stays pure).
- Acceptance: unit tests for every validation branch and both tool
  listings; existing 139 tests stay green.

### P1 — Server wiring: sockets, push, bounded confirm (offline)

- page_id → socket map maintained by `handle_ws`; downstream command
  frame `{"type": "command", "command_id", "op": "set_widget_text",
  "widget", "text"}` sent only to the active page's socket;
- `tools/call` handler: validate via commands.py against the live
  envelope, CAS, enqueue, push, poll the mailbox revision with a ~3 s
  bound, shape the MCP result;
- offline WS tests over the real aiohttp stack (fake page applies by
  publishing a new snapshot).
- Acceptance: applied / queued / refusal paths all covered offline; no
  payload logging.

### P2 — Frontend apply

- `aiAssistant.js` handles the `command` frame: find the selected node,
  set the named text-like widget's value, trigger the widget's change
  notification, publish the fresh snapshot immediately (bypassing the
  1 s tick); ignore-and-report frames that no longer match the selection.
- Acceptance: npm tests for the pure decision core; `node --check` for
  the shell; no DOM UI.

### P3 — Live smoke

- against the running ComfyUI: Claude Code and opencode set text on a
  TextInput node; revision advances; undo works; stale revision and
  unknown widget are refused.

## Risks

- Widget change semantics differ per type (callback vs `app.graph.change`)
  — verified in the live smoke, not assumed.
- A model may call the tool without reading first: `expected_revision`
  being required forces the read.
- A user editing between read and write is exactly what the CAS catches;
  the refusal message carries the current revision for a cheap retry.
- The bounded wait must never pin the event loop: small sleeps inside the
  existing async handler only.
