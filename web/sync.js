export const SCHEMA_VERSION = "comfyui.ai-assistant.context/1";

export function sameOriginWsUrl(protocol, host, path) {
  const scheme = protocol === "http:" ? "ws://" : "wss://";
  return scheme + host + path;
}

export function nextBackoffMs(attempt) {
  const ms = 1000 * 2 ** attempt;
  return ms > 30000 ? 30000 : ms;
}

export function stableKey(body) {
  return JSON.stringify({ workflow: body.workflow, selection: body.selection });
}

export function registerMessage(pageId) {
  return { type: "register", page_id: pageId };
}

export function activateMessage(pageId) {
  return { type: "activate", page_id: pageId };
}

export function snapshotMessage(pageId, body, revision, capturedAt) {
  return {
    type: "snapshot",
    page_id: pageId,
    snapshot: {
      schema_version: SCHEMA_VERSION,
      captured_at: capturedAt,
      revision,
      workflow: body.workflow,
      selection: body.selection,
    },
  };
}

const TEXT_WIDGET_TYPES = ["text", "customtext", "string"];

export function singleSelectedNode(selectedNodes) {
  if (selectedNodes === null || selectedNodes === undefined) return null;
  if (typeof selectedNodes !== "object") return null;
  const keys = Object.keys(selectedNodes);
  if (keys.length !== 1) return null;
  const node = selectedNodes[keys[0]];
  if (node === null || typeof node !== "object") return null;
  return node;
}

export function applyWidgetText(node, widgetName, text) {
  if (
    node === null ||
    node === undefined ||
    !Array.isArray(node.widgets)
  ) {
    return { applied: false, reason: "no-widgets" };
  }
  let widget = null;
  for (const w of node.widgets) {
    if (w !== null && typeof w === "object" && w.name === widgetName) {
      widget = w;
      break;
    }
  }
  if (widget === null) return { applied: false, reason: "unknown-widget" };
  if (typeof widget.type !== "string" || !TEXT_WIDGET_TYPES.includes(widget.type)) {
    return { applied: false, reason: "not-text-like" };
  }
  widget.value = text;
  if (typeof widget.callback === "function") {
    try {
      widget.callback(text);
    } catch {
      // swallow callback exceptions; the edit still counts as applied
    }
  }
  return { applied: true };
}

export function isCommandFrame(message) {
  return (
    message !== null &&
    typeof message === "object" &&
    message.type === "command" &&
    message.op === "set_widget_text"
  );
}
