# ComfyUI-AIAssistant

`ComfyUI-AIAssistant` exposes a small, read-only snapshot of the currently
selected ComfyUI node or nodes. A local assistant can fetch that snapshot before
answering questions such as “How should I configure the selected node?”.

The first version does not render chat, call an AI service, mutate workflows,
or execute prompts. OpenCode remains the conversation UI; this extension only
provides the missing canvas context.

Development status: initial roadmap and implementation in progress.

