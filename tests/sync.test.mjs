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
