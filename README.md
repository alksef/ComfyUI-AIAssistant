# ComfyUI-AIAssistant

Let a local AI assistant see what is selected on your ComfyUI canvas — and,
on explicit request, insert text into it.

Every browser tab publishes a bounded snapshot of the current node selection
to the ComfyUI process over a same-origin WebSocket. The snapshot lives in
RAM and is served to any local consumer over HTTP or MCP. One narrow write
tool, `set_widget_text`, can insert text into a text-like widget of the
selected node, guarded by concurrency checks.

No chat UI, no AI service calls, no workflow nodes, no runtime dependencies.

## Highlights

- **Selection context for agents** — ask *"how should I configure the
  selected node?"* and get an answer grounded in the live widget values,
  input/output slots and connections.
- **MCP server built in** — one URL, no extra process: `POST /mcp` speaks a
  stateless subset of MCP Streamable HTTP (verified live with Claude Code
  and OpenCode).
- **Multi-tab aware** — every tab is a page in a bounded registry; the
  active page follows window focus and carries a label (`AI-XXXX`) shown at
  the top of the tab, so you and the agent always name the same tab.
- **Read-only by design, one narrow carve-out** — the only mutation the
  plugin can perform is writing text into one text-like widget of the
  selected node on the active page, on an explicit MCP request, guarded by
  revision and page-identity checks. On the canvas the edit behaves exactly
  like a manual widget edit: undo works, the workflow becomes dirty.
- **Private by construction** — RAM-only storage, no persistence, no
  telemetry, no outbound network requests, no payload logging; secret-like
  widget names are redacted before the snapshot leaves the page.

## Requirements

- ComfyUI with the current frontend (developed and verified against
  ComfyUI 0.33.3, frontend 1.50.6, aiohttp 3.14, Python 3.13).
- Python ≥ 3.10.
- No additional Python or Node packages.

## Install

```bash
cd <ComfyUI>/custom_nodes
git clone https://github.com/alksef/ComfyUI-AIAssistant.git
```

Restart ComfyUI. Once the frontend loads, each tab shows its page label
(for example `AI-6DEF`) at the top center of the window — that label
identifies the tab in the context envelope below.

## Connect an MCP client

The endpoint is `http://127.0.0.1:8188/mcp` — the ComfyUI port, Streamable
HTTP transport, stateless. Adjust the host/port if your ComfyUI listens
elsewhere.

### Claude Code

```bash
claude mcp add --transport http comfyui http://127.0.0.1:8188/mcp
```

Then ask: *"what is selected in ComfyUI?"* — Claude reads it through
`get_selection`.

### OpenCode

In `opencode.json`:

```json
{
  "mcp": {
    "comfyui": {
      "type": "remote",
      "url": "http://127.0.0.1:8188/mcp"
    }
  }
}
```

### Any MCP client (or plain curl)

```bash
curl -s http://127.0.0.1:8188/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"get_selection","arguments":{}}}'
```

Supported methods: `initialize`, `tools/list`, `tools/call`, `ping`.
Notifications get `202 Accepted`; `GET`/`DELETE` get `405 Allow: POST`;
bodies are capped at 64 KiB. No sessions, no SSE — one JSON-RPC message per
POST.

## Tools

### `get_selection`

Read-only, no arguments. Returns the context envelope (below) as compact
JSON in `content[0].text`. An absent snapshot (`available: false`) is a
normal result: no tab has published yet.

### `set_widget_text`

Inserts `text` into `widget` of the **currently selected node** on the
**active page**. All four parameters are required:

| Parameter          | Type    | Meaning                                              |
| ------------------ | ------- | ---------------------------------------------------- |
| `widget`           | string  | Exact widget name as `get_selection` reports it      |
| `text`             | string  | Text to insert (≤ 8192 chars)                        |
| `expected_revision`| integer | Revision you last saw — forces a read before a write |
| `expected_page`    | string  | `active_page.page_id` you last saw                   |

The revision and page checks make writes safe against a stale plan: if the
user edited something or switched tabs between your read and your write,
the call is refused with the current revision so you can re-read and retry.

Results (`content[0].text`, compact JSON):

- success — `{"status":"applied","revision":<new>,"widget":<name>}` when the
  page confirmed the edit within the bounded wait (≈3 s), or
  `{"status":"queued",...}` when the command was dispatched but no
  confirmation arrived in time;
- refusal (`isError: true`) — `invalid params …`, `no selection available`,
  `no node selected`, `multiple nodes selected`, `unknown widget`,
  `widget is not text-like`, `no active page`, `active page changed`,
  `revision mismatch` (the last two carry `current_revision` for a cheap
  retry).

Only text-like widgets (type `text`, `customtext` or `string`) of a singly
selected node can be written. Nothing else mutates: no queue, no graph
structure, no settings, no files.

## HTTP API (for scripts and debugging)

All responses carry `Cache-Control: no-store`. Bodies are capped at 128 KiB.

- `GET /ai-assistant/context` — the context envelope. Poll this per
  question if your consumer is not an MCP client.
- `POST /ai-assistant/context` — anonymous snapshot channel: submit a
  normalized snapshot object (`schema_version`, `captured_at`, `revision`,
  `workflow`, `selection`) exactly as the frontend builds it; useful for
  testing consumers without a browser. Does not create registry pages.
- `WS /ai-assistant/ws` — the frontend channel (below).

### Context envelope

```json
{
  "schema_version": "comfyui.ai-assistant.context/1",
  "available": true,
  "received_at": "2026-08-29T12:00:00.123456+00:00",
  "snapshot": {
    "schema_version": "comfyui.ai-assistant.context/1",
    "captured_at": "2026-08-29T12:00:00.120000+00:00",
    "revision": 7,
    "workflow": {
      "id": "9",
      "title": "ace_step remix",
      "selected_count": 1,
      "selection_detail": "full",
      "selected_limit": 1,
      "selection_truncated": false
    },
    "selection": [
      {
        "id": "107",
        "comfyClass": "CLIPTextEncode",
        "title": "Song Tags",
        "type": "CLIPTextEncode",
        "mode": 0,
        "widgets": [
          { "name": "text", "type": "text", "value": "K-Pop Girl Group, …",
            "truncated": false, "redacted": false, "unsupported": false }
        ],
        "inputs": [
          { "name": "clip", "type": "CLIP",
            "link": { "link_id": "42", "origin_id": "11", "origin_slot": 0,
                      "target_id": "107", "target_slot": 0, "type": "CLIP" } }
        ],
        "outputs": [
          { "name": "CONDITIONING", "type": "CONDITIONING", "links": [] }
        ]
      }
    ]
  },
  "pages": [
    { "page_id": "6def0a1b-2c3d-4e5f-8a9b-0c1d2e3f4a5b",
      "page_label": "AI-6DEF", "workflow_name": "ace_step remix",
      "connected": true }
  ],
  "active_page": { "page_id": "6def0a1b-…", "page_label": "AI-6DEF", "connected": true }
}
```

Notes:

- `selection_detail` is `full` for a single selection, `names_only` for a
  multiple selection (bounded node names, no ids/params/widgets/links),
  `none` for an empty selection — an empty selection is a *valid* snapshot.
- `revision` grows monotonically per page on every published change; use it
  with `page_id` for the `set_widget_text` checks.
- Values are bounded and normalized: strings over 512 chars truncate to
  `<truncated>`, non-JSON shapes become `<unsupported>`, and widget names
  containing terms like `password`, `token`, `api_key` are reported with
  `"<redacted>"` values.
- `active_page` is the most recently focused connected tab; when it
  disconnects, the next remaining tab takes over immediately (socket
  liveness — no timeouts).

### WebSocket channel (frontend ↔ server)

JSON text frames, one object per frame. The frontend sends `register`
(`{type, page_id}`), `snapshot` (`{type, page_id, snapshot}` — the
normalized snapshot object), `activate` (`{type, page_id}`, on focus and
visibility change), and receives `registered` / `accepted` (with the
revision) / `activated` acks, `error` frames that never close the socket,
and command frames `{type: "command", command_id, op: "set_widget_text",
widget, text}` carrying the write. The registry holds at most 8 pages;
disconnected pages are evicted first.

## Security and privacy boundary

- The plugin **stores snapshots only in process memory** and never writes
  them to disk, never logs them, never echoes them anywhere except to the
  asking consumer.
- The plugin **makes no outbound network requests**. The WebSocket is
  same-origin inbound; consumers pull context.
- Secret-like widget names are **redacted in the frontend** before the
  snapshot leaves the page; values never travel for them.
- The endpoints ride the ComfyUI port and are reachable wherever ComfyUI is
  reachable — including LAN exposure if you run ComfyUI that way. They
  expose exactly the bounded selection snapshot and the one guarded write;
  there is no authentication, so treat the port as trusted (default:
  localhost).
- The only mutation surface is the `set_widget_text` carve-out described
  above. `AGENTS.md` records this boundary for contributors.

## Limitations

- Writes target text-like widgets only, a single selection only, the active
  page only.
- `"queued"` means dispatched without confirmation in the bounded wait —
  check the revision or re-read before retrying; a concurrent manual edit
  can also advance the revision and be reported as `"applied"`.
- The MCP subset is stateless by design: no sessions, no SSE streams, no
  server-initiated notifications, no batching.

## Development

```bash
python -m unittest discover -s tests -v   # backend (needs aiohttp)
ruff check ai_assistant tests             # lint
ruff format --check ai_assistant tests    # format
npm test                                  # frontend (node:test)
```

The backend core (`pages`, `commands`, `mcp_protocol`) is stdlib-only and
fully testable offline; `server.py` is covered through aiohttp test
utilities. Design decisions and their history live in `docs/roadmaps/`.

## License

MIT — see [LICENSE](LICENSE).
