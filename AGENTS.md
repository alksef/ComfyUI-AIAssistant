# ComfyUI-AIAssistant agent guide

## Scope

This repository contains a small ComfyUI extension that exposes a bounded,
read-only snapshot of the user's current canvas selection to a local AI
assistant.

## Boundaries

- Do not add executable ComfyUI workflow nodes.
- Do not mutate the graph, widgets, queue, models, files, or ComfyUI
  settings. Single explicit carve-out (ROADMAP-003): at an agent's MCP
  request the plugin may write text into exactly one text-like widget of
  the currently selected node on the active page, guarded by revision and
  page-identity CAS and size bounds; the edit behaves like a manual widget
  edit.
- Do not persist workflow, prompt, selection, or conversation content.
- Do not make outbound network requests. Consumers pull context from the
  ComfyUI localhost API.
- The MCP endpoint `POST /mcp` is one more inbound route beside the context
  routes: beyond the guarded write tool it never mutates state, never logs
  payloads, and adds no dependencies.
- Keep runtime dependencies empty. Use APIs already shipped with ComfyUI.
- Keep the public context contract versioned and bounded.
- Never log the context payload or prompt/widget contents.

## Development workflow

- Durable decisions belong in `docs/roadmaps/`.
- Non-trivial implementation starts from a written task: goal, allowed
  files, verified facts, required behavior, acceptance commands.
- Review every diff before accepting it and run the task acceptance
  commands.
- Do not commit unless the owner explicitly asks.

## Verification

Run from the repository root:

```
python -m unittest discover -s tests -v   # backend (needs aiohttp)
ruff check ai_assistant tests
ruff format --check ai_assistant tests
npm test                                  # frontend (node:test)
node --check web/aiAssistant.js
```
