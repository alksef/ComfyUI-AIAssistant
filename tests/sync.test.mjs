import { test } from "node:test";
import assert from "node:assert/strict";
import {
  SCHEMA_VERSION,
  sameOriginWsUrl,
  nextBackoffMs,
  stableKey,
  registerMessage,
  activateMessage,
  snapshotMessage,
  singleSelectedNode,
  applyWidgetText,
  isCommandFrame,
  pageBadgeLabel,
} from "../web/sync.js";

test("SCHEMA_VERSION is the bounded context contract version", () => {
  assert.equal(SCHEMA_VERSION, "comfyui.ai-assistant.context/1");
});

test("sameOriginWsUrl maps http: to ws:// and everything else to wss://", () => {
  assert.equal(
    sameOriginWsUrl("http:", "127.0.0.1:8188", "/ai-assistant/ws"),
    "ws://127.0.0.1:8188/ai-assistant/ws"
  );
  assert.equal(
    sameOriginWsUrl("https:", "example.com", "/ai-assistant/ws"),
    "wss://example.com/ai-assistant/ws"
  );
  assert.equal(sameOriginWsUrl("file:", "localhost", "/p"), "wss://localhost/p");
});

test("nextBackoffMs doubles per attempt and caps at 30000", () => {
  assert.equal(nextBackoffMs(0), 1000);
  assert.equal(nextBackoffMs(1), 2000);
  assert.equal(nextBackoffMs(2), 4000);
  assert.equal(nextBackoffMs(3), 8000);
  assert.equal(nextBackoffMs(4), 16000);
  assert.equal(nextBackoffMs(5), 30000);
  assert.equal(nextBackoffMs(6), 30000);
  assert.equal(nextBackoffMs(100), 30000);
});

test("stableKey is stable for equal workflow/selection and changes on any change", () => {
  const base = { workflow: { id: "1", title: "T" }, selection: [{ id: 1 }] };
  assert.equal(
    stableKey(base),
    stableKey({ workflow: { id: "1", title: "T" }, selection: [{ id: 1 }] })
  );
  assert.notEqual(
    stableKey(base),
    stableKey({ workflow: { id: "2", title: "T" }, selection: [{ id: 1 }] })
  );
  assert.notEqual(
    stableKey(base),
    stableKey({ workflow: { id: "1", title: "T" }, selection: [] })
  );
});

test("stableKey ignores fields other than workflow and selection", () => {
  const base = { workflow: { id: "1" }, selection: [] };
  assert.equal(
    stableKey(base),
    stableKey({ workflow: { id: "1" }, selection: [], captured_at: "now" })
  );
});

test("registerMessage shape", () => {
  assert.deepEqual(registerMessage("page-1"), {
    type: "register",
    page_id: "page-1",
  });
});

test("activateMessage shape", () => {
  assert.deepEqual(activateMessage("page-1"), {
    type: "activate",
    page_id: "page-1",
  });
});

test("snapshotMessage shape and field spread", () => {
  const body = { workflow: { id: "1" }, selection: [{ id: 1 }] };
  const message = snapshotMessage("page-1", body, 3, "2026-08-29T00:00:00.000Z");
  assert.deepEqual(message, {
    type: "snapshot",
    page_id: "page-1",
    snapshot: {
      schema_version: SCHEMA_VERSION,
      captured_at: "2026-08-29T00:00:00.000Z",
      revision: 3,
      workflow: { id: "1" },
      selection: [{ id: 1 }],
    },
  });
});

test("snapshotMessage spreads only workflow and selection from the body", () => {
  const body = { workflow: { id: "1" }, selection: [], extra: "leak" };
  const message = snapshotMessage("p", body, 1, "t");
  assert.deepEqual(
    Object.keys(message.snapshot).sort(),
    ["captured_at", "revision", "schema_version", "selection", "workflow"]
  );
  assert.ok(!("extra" in message.snapshot));
});

test("snapshotMessage passes revision and captured_at through unchanged", () => {
  const message = snapshotMessage("p", { workflow: {}, selection: [] }, 42, "iso");
  assert.equal(message.snapshot.revision, 42);
  assert.equal(message.snapshot.captured_at, "iso");
});

test("singleSelectedNode returns the node only for exactly one own entry", () => {
  const node = { id: 1, type: "KSampler", widgets: [] };
  assert.equal(singleSelectedNode(null), null);
  assert.equal(singleSelectedNode(undefined), null);
  assert.equal(singleSelectedNode({}), null);
  assert.equal(singleSelectedNode({ 1: node, 2: { id: 2 } }), null);
  assert.equal(singleSelectedNode({ 1: "not-a-node" }), null);
  assert.equal(singleSelectedNode(node), null);
  assert.equal(singleSelectedNode({ 1: node }), node);
});

test("applyWidgetText rejects unknown, non-text-like and missing widgets", () => {
  const node = {
    widgets: [
      { name: "text_widget", type: "text", value: "old" },
      { name: "num_widget", type: "number", value: 5 },
    ],
  };
  assert.deepEqual(applyWidgetText(node, "missing", "x"), {
    applied: false,
    reason: "unknown-widget",
  });
  assert.deepEqual(applyWidgetText(node, "num_widget", "x"), {
    applied: false,
    reason: "not-text-like",
  });
  assert.deepEqual(applyWidgetText({}, "anything", "x"), {
    applied: false,
    reason: "no-widgets",
  });
  assert.deepEqual(applyWidgetText(null, "anything", "x"), {
    applied: false,
    reason: "no-widgets",
  });
  assert.deepEqual(applyWidgetText({ widgets: "not-an-array" }, "a", "x"), {
    applied: false,
    reason: "no-widgets",
  });
});

test("applyWidgetText applies text and calls the callback with it", () => {
  const calls = [];
  const node = {
    widgets: [
      {
        name: "prompt",
        type: "customtext",
        value: "before",
        callback: (t) => calls.push(t),
      },
    ],
  };
  const result = applyWidgetText(node, "prompt", "after");
  assert.deepEqual(result, { applied: true });
  assert.equal(node.widgets[0].value, "after");
  assert.deepEqual(calls, ["after"]);
  assert.equal(node.widgets[0].name, "prompt");

  const noCallback = { widgets: [{ name: "w", type: "string", value: "" }] };
  assert.deepEqual(applyWidgetText(noCallback, "w", "set"), { applied: true });
  assert.equal(noCallback.widgets[0].value, "set");
});

test("applyWidgetText swallows throwing callbacks and still reports applied", () => {
  const node = {
    widgets: [
      {
        name: "w",
        type: "text",
        value: "",
        callback: () => {
          throw new Error("boom");
        },
      },
    ],
  };
  let result;
  assert.doesNotThrow(() => {
    result = applyWidgetText(node, "w", "new");
  });
  assert.deepEqual(result, { applied: true });
  assert.equal(node.widgets[0].value, "new");
});

test("pageBadgeLabel is the deterministic uppercase 4-char prefix", () => {
  assert.equal(pageBadgeLabel("e48e94c1-3115-4d0f-9a2b-1234567890ab"), "AI-E48E");
});

test("pageBadgeLabel returns null for short, non-string and empty input", () => {
  assert.equal(pageBadgeLabel("abc"), null);
  assert.equal(pageBadgeLabel(null), null);
  assert.equal(pageBadgeLabel(42), null);
  assert.equal(pageBadgeLabel(""), null);
});

test("isCommandFrame matches only the exact set_widget_text command frame", () => {
  assert.equal(
    isCommandFrame({ type: "command", op: "set_widget_text", widget: "p", text: "x" }),
    true
  );
  assert.equal(isCommandFrame({ type: "registered" }), false);
  assert.equal(isCommandFrame({ type: "accepted" }), false);
  assert.equal(isCommandFrame({ type: "activated" }), false);
  assert.equal(isCommandFrame({ type: "error" }), false);
  assert.equal(isCommandFrame({ type: "command", op: "other" }), false);
  assert.equal(isCommandFrame({ type: "command" }), false);
  assert.equal(isCommandFrame("command"), false);
  assert.equal(isCommandFrame(null), false);
  assert.equal(isCommandFrame(42), false);
  assert.equal(isCommandFrame([{ type: "command", op: "set_widget_text" }]), false);
});
