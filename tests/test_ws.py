"""WebSocket context-sync contract tests over the real aiohttp stack.

The server module is loaded the same way ``test_server.py`` does it: a fake
``server`` module is installed in ``sys.modules`` first, then the repository
root ``__init__.py`` is imported under a unique module name. WebSocket
handlers cannot run on the ``FakeRequest`` harness, so each test serves a real
``aiohttp`` application (WS handler registered directly) through
``aiohttp.test_utils.TestServer`` / ``TestClient`` inside an
``unittest.IsolatedAsyncioTestCase``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path

from aiohttp import test_utils, web

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ROOT_MODULE_NAME = "_comfyui_ai_assistant_ws_test"

_POST_HEADERS = {"Content-Type": "application/json"}


class FakeRouteTable:
    def __init__(self) -> None:
        self.routes: list[tuple[str, str, object]] = []

    def route(self, method: str, path: str):
        def decorator(handler: object):
            self.routes.append((method, path, handler))
            return handler

        return decorator

    def get(self, path: str):
        return self.route("GET", path)

    def post(self, path: str):
        return self.route("POST", path)


class FakePromptServer:
    def __init__(self) -> None:
        self.routes = FakeRouteTable()


def _load_root_entrypoint():
    path = _REPO_ROOT / "__init__.py"
    spec = importlib.util.spec_from_file_location(_ROOT_MODULE_NAME, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[_ROOT_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def setUpModule() -> None:
    if "server" not in sys.modules:
        fake_server = types.ModuleType("server")
        fake_server.PromptServer = FakePromptServer
        FakePromptServer.instance = FakePromptServer()
        sys.modules["server"] = fake_server

    global ROOT_MOD, SERVER_MOD
    if "ai_assistant" in sys.modules:
        raise AssertionError("test isolation requires no top-level ai_assistant module")
    ROOT_MOD = _load_root_entrypoint()
    SERVER_MOD = sys.modules[f"{_ROOT_MODULE_NAME}.ai_assistant.server"]


def _snapshot(**overrides: object) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "schema_version": "comfyui.ai-assistant.context/1",
        "captured_at": "2026-08-29T10:00:00+00:00",
        "revision": 1,
        "workflow": {"id": 3, "title": "KSampler"},
        "selection": [{"id": 3, "title": "KSampler"}],
    }
    snapshot.update(overrides)
    return snapshot


class WebSocketSyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        SERVER_MOD._mailbox = SERVER_MOD.ContextMailbox()
        SERVER_MOD._registry = SERVER_MOD.PageRegistry()
        SERVER_MOD._mailbox_mirrored_page = None

    async def asyncSetUp(self) -> None:
        app = web.Application()
        app.router.add_get(SERVER_MOD.CONTEXT_PATH, SERVER_MOD.handle_get)
        app.router.add_post(SERVER_MOD.CONTEXT_PATH, SERVER_MOD.handle_post)
        app.router.add_get(SERVER_MOD.WS_PATH, SERVER_MOD.handle_ws)
        self.server = test_utils.TestServer(app)
        await self.server.start_server()
        self.client = test_utils.TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        await self.server.close()

    async def _connect_ws(self):
        return await self.client.ws_connect(SERVER_MOD.WS_PATH)

    async def _get_envelope(self) -> dict[str, object]:
        response = await self.client.get(SERVER_MOD.CONTEXT_PATH)
        return await response.json()

    async def _post_snapshot(self, snapshot: dict[str, object]):
        return await self.client.post(
            SERVER_MOD.CONTEXT_PATH,
            data=json.dumps(snapshot),
            headers=_POST_HEADERS,
        )

    async def _register(self, ws, page_id: str) -> None:
        await ws.send_json({"type": "register", "page_id": page_id})
        reply = await ws.receive_json()
        self.assertEqual(reply, {"type": "registered", "ok": True})

    async def _send_snapshot(self, ws, page_id: str, revision: int) -> None:
        await ws.send_json(
            {
                "type": "snapshot",
                "page_id": page_id,
                "snapshot": _snapshot(revision=revision),
            }
        )
        reply = await ws.receive_json()
        self.assertEqual(reply, {"type": "accepted", "ok": True, "revision": revision})

    @staticmethod
    def _connected_map(body: dict[str, object]) -> dict[str, bool]:
        pages = body["pages"]
        return {page["page_id"]: page["connected"] for page in pages}

    async def test_fresh_module_envelope_before_any_ws_traffic(self):
        body = await self._get_envelope()
        self.assertIs(body["available"], False)
        self.assertIsNone(body["snapshot"])
        self.assertEqual(body["pages"], [])
        self.assertIsNone(body["active_page"])

    async def test_register_and_snapshot_over_ws_served_by_get(self):
        ws = await self._connect_ws()
        try:
            await self._register(ws, "tab-a")
            await self._send_snapshot(ws, "tab-a", 7)
            body = await self._get_envelope()
            self.assertIs(body["available"], True)
            self.assertEqual(body["snapshot"]["revision"], 7)
            self.assertEqual(
                body["pages"],
                [
                    {
                        "page_id": "tab-a",
                        "page_label": "AI-TAB-",
                        "workflow_name": "KSampler",
                        "connected": True,
                    }
                ],
            )
            self.assertEqual(
                body["active_page"],
                {"page_id": "tab-a", "page_label": "AI-TAB-", "connected": True},
            )
        finally:
            await ws.close()

    async def test_second_page_becomes_active_without_clearing_mailbox(self):
        ws1 = await self._connect_ws()
        ws2 = await self._connect_ws()
        try:
            await self._register(ws1, "tab-a")
            await self._send_snapshot(ws1, "tab-a", 7)
            await self._register(ws2, "tab-b")
            body = await self._get_envelope()
            self.assertEqual(
                body["active_page"],
                {"page_id": "tab-b", "page_label": "AI-TAB-", "connected": True},
            )
            self.assertEqual(body["snapshot"]["revision"], 7)
            await self._send_snapshot(ws2, "tab-b", 8)
            body = await self._get_envelope()
            self.assertEqual(
                body["active_page"],
                {"page_id": "tab-b", "page_label": "AI-TAB-", "connected": True},
            )
            self.assertEqual(body["snapshot"]["revision"], 8)
        finally:
            await ws1.close()
            await ws2.close()

    async def test_first_page_reactivation_restores_its_stored_snapshot(self):
        ws1 = await self._connect_ws()
        ws2 = await self._connect_ws()
        try:
            await self._register(ws1, "tab-a")
            await self._send_snapshot(ws1, "tab-a", 7)
            await self._register(ws2, "tab-b")
            await self._send_snapshot(ws2, "tab-b", 8)
            await ws1.send_json({"type": "activate", "page_id": "tab-a"})
            reply = await ws1.receive_json()
            self.assertEqual(reply, {"type": "activated", "ok": True})
            body = await self._get_envelope()
            self.assertEqual(
                body["active_page"],
                {"page_id": "tab-a", "page_label": "AI-TAB-", "connected": True},
            )
            self.assertEqual(body["snapshot"]["revision"], 7)
        finally:
            await ws1.close()
            await ws2.close()

    async def test_closing_active_page_socket_falls_back_and_mirrors(self):
        ws1 = await self._connect_ws()
        ws2 = await self._connect_ws()
        try:
            await self._register(ws1, "tab-a")
            await self._send_snapshot(ws1, "tab-a", 7)
            await self._register(ws2, "tab-b")
            await ws1.send_json({"type": "activate", "page_id": "tab-a"})
            await ws1.receive_json()
            await ws2.send_json(
                {
                    "type": "snapshot",
                    "page_id": "tab-b",
                    "snapshot": _snapshot(revision=8, workflow={"name": "Flow B"}),
                }
            )
            await ws2.receive_json()
            await ws1.close()
            body = await self._get_envelope()
            self.assertEqual(
                body["active_page"],
                {"page_id": "tab-b", "page_label": "AI-TAB-", "connected": True},
            )
            self.assertEqual(body["snapshot"]["revision"], 8)
            self.assertEqual(
                body["pages"],
                [
                    {
                        "page_id": "tab-a",
                        "page_label": "AI-TAB-",
                        "workflow_name": "KSampler",
                        "connected": False,
                    },
                    {
                        "page_id": "tab-b",
                        "page_label": "AI-TAB-",
                        "workflow_name": "Flow B",
                        "connected": True,
                    },
                ],
            )
            await ws2.close()
            body = await self._get_envelope()
            self.assertEqual(self._connected_map(body), {"tab-a": False, "tab-b": False})
            self.assertIsNone(body["active_page"])
            self.assertIs(body["available"], True)
            self.assertEqual(body["snapshot"]["revision"], 8)
        finally:
            await ws1.close()
            await ws2.close()

    async def test_invalid_snapshot_errors_without_changing_state(self):
        ws = await self._connect_ws()
        try:
            await self._register(ws, "tab-a")
            await self._send_snapshot(ws, "tab-a", 1)
            await ws.send_json(
                {
                    "type": "snapshot",
                    "page_id": "tab-a",
                    "snapshot": {"schema_version": "comfyui.ai-assistant.context/2"},
                }
            )
            reply = await ws.receive_json()
            self.assertEqual(reply["type"], "error")
            self.assertIs(reply["ok"], False)
            body = await self._get_envelope()
            self.assertEqual(body["snapshot"]["revision"], 1)
            self.assertEqual(SERVER_MOD._registry.snapshot_for("tab-a")["revision"], 1)
            await self._send_snapshot(ws, "tab-a", 2)
            body = await self._get_envelope()
            self.assertEqual(body["snapshot"]["revision"], 2)
        finally:
            await ws.close()

    async def test_unknown_and_malformed_frames_error_but_keep_socket_open(self):
        ws = await self._connect_ws()
        try:
            await ws.send_json({"type": "bogus"})
            reply = await ws.receive_json()
            self.assertEqual(reply["type"], "error")
            self.assertIs(reply["ok"], False)
            await ws.send_json([1, 2])
            reply = await ws.receive_json()
            self.assertEqual(reply["type"], "error")
            await ws.send_json("text")
            reply = await ws.receive_json()
            self.assertEqual(reply["type"], "error")
            await ws.send_str("{not json")
            reply = await ws.receive_json()
            self.assertEqual(reply["type"], "error")
            await ws.send_bytes(b"\x00\x01")
            reply = await ws.receive_json()
            self.assertEqual(reply["type"], "error")
            await self._register(ws, "tab-a")
        finally:
            await ws.close()

    async def test_post_stays_anonymous_until_ws_snapshot_replaces_it(self):
        response = await self._post_snapshot(_snapshot(revision=5))
        self.assertEqual(response.status, 200)
        body = await self._get_envelope()
        self.assertIs(body["available"], True)
        self.assertEqual(body["snapshot"]["revision"], 5)
        self.assertEqual(body["pages"], [])
        self.assertIsNone(body["active_page"])
        ws = await self._connect_ws()
        try:
            await self._register(ws, "tab-a")
            await self._send_snapshot(ws, "tab-a", 6)
            body = await self._get_envelope()
            self.assertEqual(body["snapshot"]["revision"], 6)
            self.assertEqual(
                body["active_page"],
                {"page_id": "tab-a", "page_label": "AI-TAB-", "connected": True},
            )
        finally:
            await ws.close()


if __name__ == "__main__":
    unittest.main()
