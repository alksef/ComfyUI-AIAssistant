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
