import { test } from "node:test";
import assert from "node:assert/strict";
import { buildContext } from "../web/context.js";

function link(id, originId, originSlot, targetId, targetSlot, type) {
  return { origin_id: originId, origin_slot: originSlot, target_id: targetId, target_slot: targetSlot, type };
}

function deepFreeze(value, seen) {
  seen = seen || new Set();
  if (value === null || typeof value !== "object" || seen.has(value)) return value;
  seen.add(value);
  if (Array.isArray(value)) {
    for (const item of value) deepFreeze(item, seen);
  } else {
    for (const key of Object.getOwnPropertyNames(value)) deepFreeze(value[key], seen);
  }
  return Object.freeze(value);
}

test("empty or missing canvas and empty selection", () => {
  for (const canvas of [undefined, null, {}]) {
    const ctx = buildContext(canvas);
    assert.deepEqual(Object.keys(ctx).sort(), ["selection", "workflow"]);
    assert.ok(!("schema_version" in ctx));
    assert.ok(!("captured_at" in ctx));
    assert.ok(!("revision" in ctx));
    assert.deepEqual(ctx.selection, []);
    assert.equal(ctx.workflow.selected_count, 0);
    assert.equal(ctx.workflow.selection_detail, "none");
    assert.equal(ctx.workflow.selection_truncated, false);
    assert.equal(ctx.workflow.selected_limit, 1);
  }

  const empty = buildContext({ graph: { id: 9 }, selected_nodes: {} });
  assert.deepEqual(empty.selection, []);
  assert.equal(empty.workflow.id, "9");
  assert.equal(empty.workflow.title, null);
  assert.equal(empty.workflow.selected_count, 0);

  const noGraph = buildContext({ selected_nodes: { 1: { id: 1 } } });
  assert.equal(noGraph.workflow.id, null);
  assert.equal(noGraph.workflow.title, null);
  assert.equal(noGraph.selection.length, 1);
  assert.equal(noGraph.selection[0].id, "1");
});

test("one normal selected KSampler-like node with widgets and connections", () => {
  const canvas = {
    graph: {
      id: 7,
      name: "Main Workflow",
      links: {
        "10": link(10, 2, 0, 1, 0, "MODEL"),
        "11": link(11, 2, 1, 1, 1, "CLIP"),
        "13": link(13, 5, 0, 1, 3, "LATENT"),
        "12": link(12, 1, 0, 3, 0, "LATENT"),
      },
    },
    selected_nodes: {
      1: {
        id: 1,
        type: "KSampler",
        comfyClass: "KSampler",
        title: "Sampler",
        mode: 0,
        widgets: [
          { name: "seed", type: "INT", value: 12345 },
          { name: "steps", type: "INT", value: 20 },
          { name: "cfg", type: "FLOAT", value: 7.5 },
          { name: "sampler_name", type: "COMBO", value: "euler" },
          { name: "scheduler", type: "COMBO", value: "normal" },
          { name: "denoise", type: "FLOAT", value: 1.0 },
        ],
        inputs: [
          { name: "model", type: "MODEL", link: 10 },
          { name: "positive", type: "CONDITIONING", link: 11 },
          { name: "negative", type: "CONDITIONING", link: null },
          { name: "latent_image", type: "LATENT", link: 13 },
        ],
        outputs: [{ name: "LATENT", type: "LATENT", links: [12] }],
      },
    },
  };

  const ctx = buildContext(canvas);
  assert.deepStrictEqual(ctx, {
    workflow: {
      id: "7",
      title: "Main Workflow",
      selected_count: 1,
      selection_detail: "full",
      selection_truncated: false,
      selected_limit: 1,
    },
    selection: [
      {
        id: "1",
        comfyClass: "KSampler",
        title: "Sampler",
        type: "KSampler",
        mode: 0,
        widgets: [
          { name: "cfg", type: "FLOAT", value: 7.5, truncated: false, redacted: false, unsupported: false },
          { name: "denoise", type: "FLOAT", value: 1, truncated: false, redacted: false, unsupported: false },
          { name: "sampler_name", type: "COMBO", value: "euler", truncated: false, redacted: false, unsupported: false },
          { name: "scheduler", type: "COMBO", value: "normal", truncated: false, redacted: false, unsupported: false },
          { name: "seed", type: "INT", value: 12345, truncated: false, redacted: false, unsupported: false },
          { name: "steps", type: "INT", value: 20, truncated: false, redacted: false, unsupported: false },
        ],
        inputs: [
          { name: "latent_image", type: "LATENT", link: { link_id: "13", origin_id: "5", origin_slot: 0, target_id: "1", target_slot: 3, type: "LATENT" } },
          { name: "model", type: "MODEL", link: { link_id: "10", origin_id: "2", origin_slot: 0, target_id: "1", target_slot: 0, type: "MODEL" } },
          { name: "negative", type: "CONDITIONING", link: null },
          { name: "positive", type: "CONDITIONING", link: { link_id: "11", origin_id: "2", origin_slot: 1, target_id: "1", target_slot: 1, type: "CLIP" } },
        ],
        outputs: [
          { name: "LATENT", type: "LATENT", links: [{ link_id: "12", origin_id: "1", origin_slot: 0, target_id: "3", target_slot: 0, type: "LATENT" }] },
        ],
      },
    ],
  });
});

test("deterministic output regardless of source insertion order", () => {
  const forward = {
    graph: {
      id: 42,
      name: "G",
      links: {
        "5": link(5, 2, 0, 1, 0, "MODEL"),
        "6": link(6, 1, 0, 3, 0, "LATENT"),
      },
    },
    selected_nodes: {
      2: {
        id: 2,
        type: "TypeB",
        title: "B",
        mode: 0,
        widgets: [{ name: "w", type: "INT", value: { b: 2, a: 1 } }],
        inputs: [{ name: "in", type: "MODEL", link: 5 }],
        outputs: [{ name: "out", type: "LATENT", links: [6] }],
      },
      1: {
        id: 1,
        type: "TypeA",
        title: "A",
        mode: 0,
        widgets: [
          { name: "x", type: "INT", value: 1 },
          { name: "y", type: "FLOAT", value: 2.5 },
        ],
        inputs: [],
        outputs: [],
      },
    },
  };

  const backward = {
    graph: {
      name: "G",
      links: {
        "6": link(6, 1, 0, 3, 0, "LATENT"),
        "5": link(5, 2, 0, 1, 0, "MODEL"),
      },
      id: 42,
    },
    selected_nodes: {
      1: {
        outputs: [],
        inputs: [],
        mode: 0,
        widgets: [
          { name: "y", type: "FLOAT", value: 2.5 },
          { name: "x", type: "INT", value: 1 },
        ],
        title: "A",
        type: "TypeA",
        id: 1,
      },
      2: {
        outputs: [{ name: "out", type: "LATENT", links: [6] }],
        inputs: [{ name: "in", type: "MODEL", link: 5 }],
        mode: 0,
        widgets: [{ name: "w", type: "INT", value: { a: 1, b: 2 } }],
        title: "B",
        type: "TypeB",
        id: 2,
      },
    },
  };

  assert.equal(
    JSON.stringify(buildContext(forward)),
    JSON.stringify(buildContext(backward))
  );

  assert.deepStrictEqual(buildContext(forward), {
    workflow: {
      id: "42",
      title: "G",
      selected_count: 2,
      selection_detail: "names_only",
      selection_truncated: false,
      selected_limit: 1,
    },
    selection: ["A", "B"],
  });
});

test("multiple selection returns names only", () => {
  const ids = "ABCDEFGHIJKLMNOPQRST".split("");
  const nodes = {};
  for (const id of ids) {
    nodes[id] = {
      id,
      title: `Node ${id}`,
      type: "TestNode",
      widgets: [{ name: "secret", value: `value-${id}` }],
      inputs: [{ name: "input", link: 1 }],
      outputs: [{ name: "output", links: [2] }],
    };
  }

  const ctx = buildContext({ graph: { id: 1 }, selected_nodes: nodes });
  assert.equal(ctx.workflow.selected_count, 20);
  assert.equal(ctx.workflow.selection_detail, "names_only");
  assert.equal(ctx.workflow.selection_truncated, false);
  assert.deepEqual(ctx.selection, ids.map((id) => `Node ${id}`));
  const json = JSON.stringify(ctx);
  assert.ok(!json.includes("value-"));
  assert.ok(!json.includes("widgets"));
  assert.ok(!json.includes("inputs"));
  assert.ok(!json.includes("outputs"));
});

test("one detailed node stays below the transport budget", () => {
  const node = {
    id: 1,
    type: "T".repeat(200),
    title: "N".repeat(200),
    widgets: Array.from({ length: 100 }, (_, i) => ({
      name: "w".repeat(200) + i,
      type: "STRING",
      value: {
        a: "😀".repeat(1000),
        b: "x".repeat(1000),
        c: "y".repeat(1000),
        d: "z".repeat(1000),
      },
    })),
    inputs: Array.from({ length: 100 }, (_, i) => ({
      name: "i".repeat(200) + i,
      type: "X".repeat(200),
      link: null,
    })),
    outputs: Array.from({ length: 100 }, (_, i) => ({
      name: "o".repeat(200) + i,
      type: "Y".repeat(200),
      links: [],
    })),
  };

  const ctx = buildContext({ graph: { id: 1 }, selected_nodes: { 1: node } });
  const bytes = new TextEncoder().encode(JSON.stringify(ctx)).length;
  assert.ok(bytes <= 98_304, `single-node context is too large: ${bytes} bytes`);
  assert.equal(ctx.workflow.selection_detail, "full");
  assert.equal(ctx.selection.length, 1);
});

test("secret-like widget names are redacted without leaking any content", () => {
  const secretNames = [
    "password",
    "Password123",
    "passwd",
    "secret",
    "client_secret",
    "token",
    "bearer_token",
    "api_key",
    "APIKEY",
    "api key",
    "authorization",
    "Bearer",
    "cookie",
    "credential",
    "private key",
    "PRIVATE_KEY",
  ];
  const widgets = secretNames.map((name, i) => ({
    name,
    type: "STRING",
    value: `SUPERSECRETVALUE_${i}_${name}`,
  }));
  widgets.push({ name: "seed", type: "INT", value: 42 });

  const canvas = {
    graph: { links: {} },
    selected_nodes: {
      1: { id: 1, type: "T", widgets, inputs: [], outputs: [] },
    },
  };

  const ctx = buildContext(canvas);
  const json = JSON.stringify(ctx);
  assert.ok(!json.includes("SUPERSECRET"), "redacted value leaked into output");

  const byName = Object.fromEntries(ctx.selection[0].widgets.map((w) => [w.name, w]));
  for (const name of secretNames) {
    const row = byName[name];
    assert.ok(row, `missing widget ${name}`);
    assert.equal(row.value, "<redacted>");
    assert.equal(row.redacted, true);
    assert.equal(row.truncated, false);
    assert.equal(row.unsupported, false);
  }
  const seed = byName.seed;
  assert.equal(seed.value, 42);
  assert.equal(seed.redacted, false);
});

test("long strings, arrays, objects, deep nesting and widget count bounds", () => {
  const widgets = [
    { name: "deep_object", type: "OBJ", value: { l1: { l2: { l3: { l4: "deep" } } } } },
    { name: "long_string", type: "STRING", value: "x".repeat(5000) },
    { name: "long_array", type: "LIST", value: Array.from({ length: 100 }, (_, i) => i) },
    { name: "wide_object", type: "OBJ", value: Object.fromEntries(Array.from({ length: 50 }, (_, i) => ["k" + i, i])) },
  ];
  const canvas = {
    graph: {},
    selected_nodes: { 1: { id: 1, type: "T", widgets, inputs: [], outputs: [] } },
  };

  const ctx = buildContext(canvas);
  const json = JSON.stringify(ctx);
  assert.ok(json.length < 5000, `output not bounded: ${json.length} bytes`);
  const byName = Object.fromEntries(ctx.selection[0].widgets.map((w) => [w.name, w]));

  assert.equal(byName.long_string.value, "<truncated>");
  assert.equal(byName.long_string.truncated, true);

  assert.equal(byName.long_array.value.length, 4);
  assert.deepEqual(byName.long_array.value, Array.from({ length: 4 }, (_, i) => i));
  assert.equal(byName.long_array.truncated, true);

  const wide = byName.wide_object;
  assert.equal(Object.keys(wide.value).length, 4);
  assert.equal(wide.truncated, true);
  const wideKeys = Object.keys(wide.value);
  for (let i = 1; i < wideKeys.length; i++) {
    assert.ok(wideKeys[i - 1] < wideKeys[i], "object keys not sorted");
  }
  assert.ok("k0" in wide.value);
  assert.ok(!("k49" in wide.value), "truncated object key leaked");

  assert.deepEqual(byName.deep_object.value, { l1: { l2: "<truncated>" } });
  assert.equal(byName.deep_object.truncated, true);

  const manyWidgets = Array.from({ length: 70 }, (_, i) => ({
    name: "w" + String(i).padStart(2, "0"),
    type: "INT",
    value: i,
  }));
  const many = buildContext({
    graph: {},
    selected_nodes: { 1: { id: 1, type: "T", widgets: manyWidgets, inputs: [], outputs: [] } },
  });
  assert.equal(many.selection[0].widgets.length, 24);
});

test("cyclic, custom-class, function and binary-like values degrade without throwing", () => {
  class CustomClass {
    constructor() {
      this.secretField = "CUSTOMLEAK";
    }
  }
  const cyclic = {};
  cyclic.self = cyclic;

  const widgets = [
    { name: "cyclic", type: "", value: cyclic },
    { name: "fn", type: "", value: function f() {} },
    { name: "arrow", type: "", value: () => 1 },
    { name: "custom", type: "", value: new CustomClass() },
    { name: "binary", type: "", value: new Uint8Array([1, 2, 3]) },
    { name: "buffer", type: "", value: new ArrayBuffer(8) },
    { name: "date", type: "", value: new Date(0) },
    { name: "map", type: "", value: new Map([["k", "v"]]) },
    { name: "set", type: "", value: new Set([1, 2]) },
    { name: "bigint", type: "", value: 123456789012345678901234567890n },
    { name: "symbol", type: "", value: Symbol("secret-sym") },
    { name: "nan", type: "", value: NaN },
    { name: "infinity", type: "", value: Infinity },
    { name: "neg_infinity", type: "", value: -Infinity },
    { name: "nullproto", type: "", value: Object.assign(Object.create(null), { z: 3, a: 1 }) },
    { name: "undefined", type: "", value: undefined },
    { name: "plain", type: "", value: "fine" },
  ];

  const ctx = buildContext({
    graph: {},
    selected_nodes: { 1: { id: 1, type: "T", widgets, inputs: [], outputs: [] } },
  });

  const json = JSON.stringify(ctx);
  assert.ok(!json.includes("CUSTOMLEAK"), "custom class field leaked");
  assert.ok(!json.includes("secret-sym"), "symbol description leaked");
  assert.ok(!json.includes("Uint8Array"), "binary type leaked");
  assert.ok(!json.includes("[object"), "default toString leaked");
  assert.ok(!json.includes("=>"), "function source leaked");

  const byName = Object.fromEntries(ctx.selection[0].widgets.map((w) => [w.name, w]));

  assert.deepEqual(byName.cyclic.value, { self: { self: "<truncated>" } });
  assert.equal(byName.cyclic.truncated, true);

  for (const name of [
    "fn",
    "arrow",
    "custom",
    "binary",
    "buffer",
    "date",
    "map",
    "set",
    "bigint",
    "symbol",
    "nan",
    "infinity",
    "neg_infinity",
  ]) {
    assert.equal(byName[name].value, "<unsupported>", `${name} should be unsupported`);
    assert.equal(byName[name].unsupported, true, `${name} should flag unsupported`);
  }

  assert.deepEqual(byName.nullproto.value, { a: 1, z: 3 });
  assert.equal(byName.undefined.value, null);
  assert.equal(byName.plain.value, "fine");
});

test("malformed or missing link and slot structures degrade safely", () => {
  const node = {
    id: 1,
    type: "T",
    widgets: "not-an-array",
    inputs: [
      { name: "missing_link", type: "MODEL", link: 999 },
      { name: "no_link", type: "MODEL", link: null },
      { name: "partial" },
      { name: "object_link", type: "MODEL", link: { evil: true } },
      "garbage-input",
    ],
    outputs: [
      { name: "null_links", type: "LATENT", links: null },
      { name: "missing_links", type: "LATENT", links: [1, 999] },
      { name: "not_array", type: "LATENT", links: "nope" },
      "garbage-output",
    ],
  };

  const ctx = buildContext({ graph: { id: 1 }, selected_nodes: { 1: node } });
  const row = ctx.selection[0];
  assert.deepEqual(row.widgets, []);
  assert.deepEqual(row.inputs.map((i) => i.name), ["missing_link", "no_link", "object_link", "partial"]);
  for (const input of row.inputs) assert.equal(input.link, null);
  assert.equal(row.inputs.find((i) => i.name === "partial").type, null);
  assert.deepEqual(row.outputs.map((o) => o.name), ["missing_links", "not_array", "null_links"]);
  for (const output of row.outputs) assert.deepEqual(output.links, []);
});

test("map-like graph links resolve and output links sort by id", () => {
  const links = new Map([
    [10, link(10, 2, 0, 1, 0, "MODEL")],
    [12, link(12, 1, 0, 3, 0, "LATENT")],
    [11, link(11, 1, 1, 4, 0, "LATENT")],
  ]);
  const canvas = {
    graph: { id: 1, links },
    selected_nodes: {
      1: {
        id: 1,
        type: "T",
        widgets: [],
        inputs: [{ name: "model", type: "MODEL", link: 10 }],
        outputs: [{ name: "out", type: "LATENT", links: [12, 11, 99] }],
      },
    },
  };

  const ctx = buildContext(canvas);
  const row = ctx.selection[0];
  assert.deepEqual(row.inputs[0].link, {
    link_id: "10",
    origin_id: "2",
    origin_slot: 0,
    target_id: "1",
    target_slot: 0,
    type: "MODEL",
  });
  const outLinks = row.outputs[0].links;
  assert.deepEqual(outLinks.map((l) => l.link_id), ["11", "12"]);
  assert.equal(outLinks.length, 2);
});

test("source canvas, node, widget and graph objects are never mutated", () => {
  const canvas = {
    graph: {
      id: 1,
      name: "G",
      links: { "5": link(5, 2, 0, 1, 0, "MODEL") },
    },
    selected_nodes: {
      1: {
        id: 1,
        type: "T",
        title: "N",
        mode: 0,
        widgets: [{ name: "seed", type: "INT", value: 7 }],
        inputs: [{ name: "model", type: "MODEL", link: 5 }],
        outputs: [{ name: "out", type: "LATENT", links: [5] }],
      },
    },
  };
  const before = JSON.stringify(canvas);
  deepFreeze(canvas);

  const ctx = buildContext(canvas);
  assert.equal(JSON.stringify(canvas), before);
  assert.equal(ctx.selection[0].widgets[0].value, 7);
  assert.equal(ctx.selection[0].inputs[0].link.link_id, "5");
});
