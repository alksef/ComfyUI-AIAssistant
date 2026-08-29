import { app } from "/scripts/app.js";
import { buildContext } from "./context.js";
import {
  sameOriginWsUrl,
  nextBackoffMs,
  stableKey,
  registerMessage,
  activateMessage,
  snapshotMessage,
  singleSelectedNode,
  applyWidgetText,
  isCommandFrame,
} from "./sync.js";

const SYNC_PATH = "/ai-assistant/ws";
const SYNC_INTERVAL_MS = 1000;

app.registerExtension({
  name: "ComfyUI-AIAssistant.ContextSync",
  setup() {
    const pageId = crypto.randomUUID();
    let socket = null;
    let attempt = 0;
    let revision = 0;
    let sentKey = null;
    let pendingBody = null;
    let reconnectTimer = null;

    function isOpen() {
      return socket !== null && socket.readyState === WebSocket.OPEN;
    }

    function send(message) {
      if (isOpen()) socket.send(JSON.stringify(message));
    }

    function sendSnapshotFor(body) {
      revision += 1;
      send(
        snapshotMessage(pageId, body, revision, new Date().toISOString())
      );
      sentKey = stableKey(body);
    }

    function tick() {
      if (!app.canvas) return;
      const body = buildContext(app.canvas);
      const key = stableKey(body);
      if (key === sentKey) {
        pendingBody = null;
        return;
      }
      if (!isOpen()) {
        pendingBody = body;
        return;
      }
      sendSnapshotFor(body);
    }

    function openSocket() {
      try {
        socket = new WebSocket(
          sameOriginWsUrl(location.protocol, location.host, SYNC_PATH)
        );
      } catch {
        console.warn("ComfyUI-AIAssistant: failed to open context sync socket");
        scheduleReconnect();
        return;
      }
      socket.addEventListener("open", () => {
        attempt = 0;
        send(registerMessage(pageId));
        send(activateMessage(pageId));
        if (pendingBody !== null) {
          const body = pendingBody;
          pendingBody = null;
          sendSnapshotFor(body);
        }
      });
      socket.addEventListener("close", () => {
        socket = null;
        scheduleReconnect();
      });
      socket.addEventListener("error", () => {
        console.warn("ComfyUI-AIAssistant: context sync socket error");
      });
      socket.addEventListener("message", (event) => {
        let frame;
        try {
          frame = JSON.parse(event.data);
        } catch {
          return;
        }
        if (!isCommandFrame(frame) || !isOpen()) return;
        try {
          const node = singleSelectedNode(app.canvas?.selected_nodes);
          if (node === null) return;
          const result = applyWidgetText(node, frame.widget, frame.text);
          if (!result.applied) return;
          try {
            app.graph.change();
          } catch {
            // never throw from the listener
          }
          sendSnapshotFor(buildContext(app.canvas));
        } catch {
          // never throw from the listener
        }
      });
    }

    function scheduleReconnect() {
      if (reconnectTimer !== null) return;
      const delay = nextBackoffMs(attempt);
      attempt += 1;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        openSocket();
      }, delay);
    }

    openSocket();
    window.setInterval(tick, SYNC_INTERVAL_MS);

    window.addEventListener("focus", () => {
      send(activateMessage(pageId));
    });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") send(activateMessage(pageId));
    });
  },
});
