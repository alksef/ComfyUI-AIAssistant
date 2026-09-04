---
id: ROADMAP-004
status: in-progress
created: 2026-09-04
updated: 2026-09-04
---

# ROADMAP-004 — Full widget text on demand

## Goal

Keep the default selection envelope small while making the full text of a
long widget (a prompt) available on demand. Long string values become a
preview plus a total length in the default envelope; a new read handle
returns the whole stored value, paged, to any MCP client or HTTP consumer.
The plugin stays consumer-agnostic: MCP clients talk to it directly, aria
is just one of them.

## Why

Real prompt widgets routinely exceed the old 512-character cap, and the
old behavior replaced the whole value with `<truncated>`, so the consumer
could not even see the beginning. But shipping every prompt in full on
every turn bloats every consumer's context. Preview by default, full text
on explicit request.

## Product boundary

```text
[page]  context.js: widget strings travel whole up to 32,768 chars
        (prefix + "…" beyond, plus a `length` field); nested strings
        keep the tight 512 cap; WS frame limit raised to 4 MiB so a
        big snapshot never breaks the sync
          ↓ WS snapshot (unchanged protocol)
[server] mailbox stores the full values (RAM, one snapshot)
          ↓
        _context_envelope() renders the DEFAULT view: string values
        longer than 512 chars become prefix + "…" with `length` set
          ↓ GET /ai-assistant/context        (preview view)
          ↓ POST /mcp → get_selection        (same preview view)
        full text handle reads the MAILBOX, not the envelope:
          ↓ GET /ai-assistant/widget-text?widget=&offset=&limit=
          ↓ POST /mcp → get_widget_text(widget, offset?, limit?)
[any consumer: MCP client, aria, scripts]
```

No new WS message types, no page round-trip: the full text is already in
the mailbox snapshot, the handle is a second view over the same data.

## In scope

- preview policy server-side only: the browser snapshot keeps full values
  (per-string transport clip 32,768 chars), the envelope builder previews
  strings longer than 512 chars (`value` = first 511 chars + `…`, additive
  `length` = total characters); everything that arrived whole before
  still arrives whole — the change only replaces what used to be
  `<truncated>`;
- one MCP tool `get_widget_text(widget, offset?, limit?)`: required
  `widget` (exact name as `get_selection` reports), optional `offset`
  (default 0) and `limit` (default and maximum 32,768);
- one HTTP twin `GET /ai-assistant/widget-text` with the same params as
  query arguments, same response body, `no-store`;
- both read the active mailbox snapshot: single selection
  (`selection_detail: full`), text-like widget types (`text`,
  `customtext`, `string`), response carries `revision`, `widget`,
  `offset`, `limit`, `length`, `text`, and `truncated` (more text beyond
  `offset + limit`);
- WS `max_msg_size` 128 KiB → 4 MiB (worst-case snapshot after the
  32,768-char clip stays under ~2 MiB);
- transport clip in `context.js`: top-level widget strings are clipped at
  32,768 chars with a `length` field; nested strings (inside objects and
  arrays) keep the 512-char `<truncated>` marker.

## Non-goals

- no LLM/tool-loop policy on the consumer side — the plugin only offers
  the handle; deciding when to call it belongs to the consumer (aria's
  preview-plus-confirmation flow lives in the aria repo);
- no paging state: offset/limit are stateless, the caller drives them;
- no reading beyond the transport clip: text longer than 32,768 chars
  does not exist server-side (raising it would need a larger WS frame
  budget; revisit if real workflows hit it);
- no changes to `get_selection`'s shape beyond the previewed values and
  the additive `length` field; `set_widget_text` is untouched.

## Tool contract

`get_widget_text` params: `{widget: string, offset?: int >= 0,
limit?: int 1..32768}`. Results:

- success: `{content: [{type: "text", text: "<payload json>"}],
  isError: false}` with payload `{"revision": <int>, "widget": <name>,
  "offset": <int>, "limit": <int>, "length": <int>, "text": <slice>,
  "truncated": <bool>}`;
- refusals (isError: true, static messages): invalid params shape;
  invalid params keys; invalid widget name; invalid offset; invalid
  limit; no selection available; no node selected; multiple nodes
  selected; unknown widget; widget is not text-like.

The HTTP route answers with the same payload JSON (200) or the same
error strings (400 for bad params, 404 for selection/widget problems),
`Cache-Control: no-store` on every response.

## Compatibility

- envelope `schema_version` stays `comfyui.ai-assistant.context/1`:
  values that used to arrive whole still arrive whole; values that used
  to be the `<truncated>` marker now arrive as a preview plus `length`;
  the `length` field is additive (the page may also set it for values the
  server did not clip);
- `set_widget_text` validation reads widget names and revisions, never
  values, so the previewed envelope cannot affect writes;
- POST `/ai-assistant/context` (anonymous debug channel) is unchanged.

## Verification

- Python: unittest — preview rendering in the envelope (GET and MCP
  paths byte-identical), widget-text reader (happy path, paging,
  offset/limit validation, selection states, widget typing), tools/list
  grows to three tools, MCP dispatch of the new tool;
- JS: node --test — 32,768-char clip with `length`, nested 512 marker
  unchanged, transport budget test for a maximal snapshot;
- live smoke after install: select a node with a long prompt, check the
  preview in GET, page the full text through the MCP tool and the HTTP
  route.
