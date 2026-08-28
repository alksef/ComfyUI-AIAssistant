const MAX_MULTIPLE_NAMES = 64;
const MAX_WIDGETS = 24;
const MAX_DEPTH = 1;
const MAX_ARRAY_LENGTH = 4;
const MAX_OBJECT_KEYS = 4;
const MAX_STRING_LENGTH = 512;
const MAX_FIELD_LENGTH = 128;
const MAX_SLOTS = 24;
const MAX_LINKS = 8;

const REDACTED = "<redacted>";
const UNSUPPORTED = "<unsupported>";
const TRUNCATED = "<truncated>";

const SECRET_TERMS = [
  "password",
  "passwd",
  "secret",
  "token",
  "api key",
  "api_key",
  "apikey",
  "authorization",
  "bearer",
  "cookie",
  "credential",
  "private key",
  "private_key",
  "privatekey",
];

export function buildContext(canvas) {
  try {
    const graph = safeRead(canvas, "graph");
    const selectedNodes = safeRead(canvas, "selected_nodes");
    const collected = collectNodes(selectedNodes);
    const total = collected.length;
    const multiple = total > 1;

    const workflow = {
      id: boundString(safeRead(graph, "id")),
      title: graphTitle(graph),
      selected_count: total,
      selection_detail: total === 0 ? "none" : multiple ? "names_only" : "full",
      selection_truncated: multiple && total > MAX_MULTIPLE_NAMES,
      selected_limit: 1,
    };

    if (multiple) {
      const selection = collected.map(nodeName).sort().slice(0, MAX_MULTIPLE_NAMES);
      return { workflow, selection };
    }

    if (total === 0) return { workflow, selection: [] };

    const graphLinks = safeRead(graph, "links");
    const selection = [buildNodeRow(collected[0], graphLinks)];

    return { workflow, selection };
  } catch {
    return {
      workflow: {
        id: null,
        title: null,
        selected_count: 0,
        selection_detail: "none",
        selection_truncated: false,
        selected_limit: 1,
      },
      selection: [],
    };
  }
}

function nodeName(node) {
  for (const key of ["title", "type", "comfyClass"]) {
    const value = boundString(safeRead(node, key));
    if (value) return value;
  }
  return "Unnamed node";
}

function collectNodes(selectedNodes) {
  const nodes = [];
  if (selectedNodes === null || selectedNodes === undefined) return nodes;
  try {
    if (Object.prototype.toString.call(selectedNodes) === "[object Map]") {
      for (const [, node] of selectedNodes) {
        if (node !== null && typeof node === "object") nodes.push(node);
      }
    } else if (Array.isArray(selectedNodes)) {
      for (const node of selectedNodes) {
        if (node !== null && typeof node === "object") nodes.push(node);
      }
    } else if (typeof selectedNodes === "object") {
      for (const key of Object.keys(selectedNodes)) {
        const node = selectedNodes[key];
        if (node !== null && typeof node === "object") nodes.push(node);
      }
    }
  } catch {
    return [];
  }
  return nodes;
}

function buildNodeRow(node, graphLinks) {
  try {
    const widgets = normalizeWidgets(safeRead(node, "widgets"));
    const inputs = normalizeInputs(safeRead(node, "inputs"), graphLinks);
    const outputs = normalizeOutputs(safeRead(node, "outputs"), graphLinks);
    return {
      id: boundString(safeRead(node, "id")),
      comfyClass: boundString(safeRead(node, "comfyClass")),
      title: boundString(safeRead(node, "title")),
      type: boundString(safeRead(node, "type")),
      mode: boundNumber(safeRead(node, "mode")),
      widgets,
      inputs,
      outputs,
    };
  } catch {
    return {
      id: null,
      comfyClass: null,
      title: null,
      type: null,
      mode: null,
      widgets: [],
      inputs: [],
      outputs: [],
    };
  }
}

function normalizeWidgets(raw) {
  if (!Array.isArray(raw)) return [];
  const rows = [];
  for (const widget of raw) {
    if (widget === null || typeof widget !== "object") continue;
    rows.push(buildWidgetRow(widget));
  }
  rows.sort(compareWidgetRows);
  return rows.slice(0, MAX_WIDGETS);
}

function normalizeInputs(raw, graphLinks) {
  if (!Array.isArray(raw)) return [];
  const rows = [];
  for (const slot of raw) {
    if (slot === null || typeof slot !== "object") continue;
    rows.push(buildInputRow(slot, graphLinks));
  }
  rows.sort(compareSlotRows);
  return rows.slice(0, MAX_SLOTS);
}

function normalizeOutputs(raw, graphLinks) {
  if (!Array.isArray(raw)) return [];
  const rows = [];
  for (const slot of raw) {
    if (slot === null || typeof slot !== "object") continue;
    rows.push(buildOutputRow(slot, graphLinks));
  }
  rows.sort(compareSlotRows);
  return rows.slice(0, MAX_SLOTS);
}

function buildWidgetRow(widget) {
  const name = boundString(safeRead(widget, "name"));
  const type = boundString(safeRead(widget, "type"));
  if (isSecretName(name)) {
    return {
      name,
      type,
      value: REDACTED,
      truncated: false,
      redacted: true,
      unsupported: false,
    };
  }
  const normalized = normalizeValue(safeRead(widget, "value"), 0);
  return {
    name,
    type,
    value: normalized.value,
    truncated: normalized.truncated,
    redacted: false,
    unsupported: normalized.unsupported,
  };
}

function buildInputRow(slot, graphLinks) {
  try {
    return {
      name: boundString(safeRead(slot, "name")),
      type: boundString(safeRead(slot, "type")),
      link: resolveInputLink(slot, graphLinks),
    };
  } catch {
    return { name: null, type: null, link: null };
  }
}

function buildOutputRow(slot, graphLinks) {
  try {
    return {
      name: boundString(safeRead(slot, "name")),
      type: boundString(safeRead(slot, "type")),
      links: resolveOutputLinks(slot, graphLinks),
    };
  } catch {
    return { name: null, type: null, links: [] };
  }
}

function resolveInputLink(slot, graphLinks) {
  const rawId = safeRead(slot, "link");
  if (rawId === null || rawId === undefined) return null;
  const link = findLink(graphLinks, rawId);
  if (!isLinkish(link)) return null;
  return linkEndpoint(rawId, link);
}

function resolveOutputLinks(slot, graphLinks) {
  const raw = safeRead(slot, "links");
  if (!Array.isArray(raw)) return [];
  const seen = new Set();
  const ids = [];
  for (const id of raw) {
    const key = boundString(id);
    if (key === null || seen.has(key)) continue;
    seen.add(key);
    ids.push({ raw: id, key });
  }
  ids.sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
  const endpoints = [];
  for (const entry of ids) {
    const link = findLink(graphLinks, entry.raw);
    if (isLinkish(link)) endpoints.push(linkEndpoint(entry.key, link));
    if (endpoints.length >= MAX_LINKS) break;
  }
  return endpoints;
}

function findLink(graphLinks, rawId) {
  const key = boundString(rawId);
  if (key === null) return undefined;
  const link = getLink(graphLinks, key);
  if (isLinkish(link)) return link;
  if (rawId !== key) {
    const alt = getLink(graphLinks, rawId);
    if (isLinkish(alt)) return alt;
  }
  return undefined;
}

function getLink(graphLinks, key) {
  if (graphLinks === null || graphLinks === undefined) return undefined;
  try {
    if (
      typeof graphLinks.get === "function" &&
      Object.prototype.toString.call(graphLinks) === "[object Map]"
    ) {
      return graphLinks.get(key);
    }
    return graphLinks[key];
  } catch {
    return undefined;
  }
}

function isLinkish(link) {
  return link !== null && typeof link === "object";
}

function linkEndpoint(rawId, link) {
  return {
    link_id: boundString(rawId),
    origin_id: boundString(safeRead(link, "origin_id")),
    origin_slot: boundNumber(safeRead(link, "origin_slot")),
    target_id: boundString(safeRead(link, "target_id")),
    target_slot: boundNumber(safeRead(link, "target_slot")),
    type: boundString(safeRead(link, "type")),
  };
}

function normalizeValue(value, depth) {
  if (depth > MAX_DEPTH) {
    return { value: TRUNCATED, truncated: true, unsupported: false };
  }
  const t = typeof value;
  if (value === null) return { value: null, truncated: false, unsupported: false };
  if (t === "string") {
    if (value.length > MAX_STRING_LENGTH) {
      return { value: TRUNCATED, truncated: true, unsupported: false };
    }
    return { value, truncated: false, unsupported: false };
  }
  if (t === "number") {
    if (Number.isFinite(value)) return { value, truncated: false, unsupported: false };
    return { value: UNSUPPORTED, truncated: false, unsupported: true };
  }
  if (t === "boolean") return { value, truncated: false, unsupported: false };
  if (t === "undefined") return { value: null, truncated: false, unsupported: false };
  if (t === "bigint" || t === "symbol" || t === "function") {
    return { value: UNSUPPORTED, truncated: false, unsupported: true };
  }
  try {
    if (Array.isArray(value)) return normalizeArray(value, depth + 1);
    if (isPlainObject(value)) return normalizeObject(value, depth + 1);
  } catch {
    return { value: UNSUPPORTED, truncated: false, unsupported: true };
  }
  return { value: UNSUPPORTED, truncated: false, unsupported: true };
}

function normalizeArray(value, depth) {
  const length = value.length;
  const truncated = length > MAX_ARRAY_LENGTH;
  const limit = truncated ? MAX_ARRAY_LENGTH : length;
  const result = [];
  let anyTruncated = truncated;
  let unsupported = false;
  for (let i = 0; i < limit; i++) {
    let item;
    try {
      item = normalizeValue(value[i], depth);
    } catch {
      item = { value: UNSUPPORTED, truncated: false, unsupported: true };
    }
    result.push(item.value);
    unsupported = unsupported || item.unsupported;
    anyTruncated = anyTruncated || item.truncated;
  }
  return { value: result, truncated: anyTruncated, unsupported };
}

function normalizeObject(value, depth) {
  const keys = Object.keys(value);
  keys.sort();
  const truncated = keys.length > MAX_OBJECT_KEYS;
  const limit = truncated ? MAX_OBJECT_KEYS : keys.length;
  const out = {};
  let anyTruncated = truncated;
  let unsupported = false;
  for (let i = 0; i < limit; i++) {
    const key = keys[i];
    const boundedKey = key.length > MAX_FIELD_LENGTH ? key.slice(0, MAX_FIELD_LENGTH) : key;
    if (boundedKey !== key) anyTruncated = true;
    let item;
    try {
      item = normalizeValue(value[key], depth);
    } catch {
      item = { value: UNSUPPORTED, truncated: false, unsupported: true };
    }
    defineDataProperty(out, boundedKey, item.value);
    unsupported = unsupported || item.unsupported;
    anyTruncated = anyTruncated || item.truncated;
  }
  return { value: out, truncated: anyTruncated, unsupported };
}

function defineDataProperty(target, key, value) {
  Object.defineProperty(target, key, {
    value,
    writable: true,
    enumerable: true,
    configurable: true,
  });
}

function isPlainObject(value) {
  if (value === null || typeof value !== "object") return false;
  const proto = Object.getPrototypeOf(value);
  if (proto === null) return true;
  const ctor = proto.constructor;
  return typeof ctor === "function" && ctor === Object;
}

function graphTitle(graph) {
  const title = safeRead(graph, "title");
  if (title !== undefined && title !== null) return boundString(title);
  const name = safeRead(graph, "name");
  if (name !== undefined && name !== null) return boundString(name);
  return null;
}

function isSecretName(name) {
  if (name === null) return false;
  const lower = name.toLowerCase();
  for (const term of SECRET_TERMS) {
    if (lower.includes(term)) return true;
  }
  return false;
}

function boundString(value) {
  if (value === null || value === undefined) return null;
  const t = typeof value;
  let text;
  if (t === "string") text = value;
  else if (t === "number") text = String(value);
  else if (t === "boolean") text = value ? "true" : "false";
  else if (t === "bigint") text = String(value);
  else return null;
  if (text.length > MAX_FIELD_LENGTH) return text.slice(0, MAX_FIELD_LENGTH);
  return text;
}

function boundNumber(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  return null;
}

function safeRead(obj, key) {
  if (obj === null || obj === undefined) return undefined;
  try {
    return obj[key];
  } catch {
    return undefined;
  }
}

function compareNodeRows(a, b) {
  const c = compareByKeys(
    [a.id ?? "", a.type ?? "", a.title ?? ""],
    [b.id ?? "", b.type ?? "", b.title ?? ""]
  );
  if (c !== 0) return c;
  return compareJson(a, b);
}

function compareWidgetRows(a, b) {
  const c = compareByKeys([a.name ?? "", a.type ?? ""], [b.name ?? "", b.type ?? ""]);
  if (c !== 0) return c;
  return compareJson(a, b);
}

const compareSlotRows = compareWidgetRows;

function compareByKeys(left, right) {
  for (let i = 0; i < left.length; i++) {
    if (left[i] < right[i]) return -1;
    if (left[i] > right[i]) return 1;
  }
  return 0;
}

function compareJson(a, b) {
  const sa = JSON.stringify(a);
  const sb = JSON.stringify(b);
  return sa < sb ? -1 : sa > sb ? 1 : 0;
}
