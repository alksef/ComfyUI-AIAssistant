"""WebSocket write-path contract tests over the real aiohttp stack.

The server module is loaded the same way ``test_ws.py`` does it: a fake
``server`` module is installed in ``sys.modules`` first, then the repository
root ``__init__.py`` is imported under a unique module name. The MCP
``set_widget_text`` tool, the page_id→socket map, and the bounded
revision-confirm wait are exercised through a real ``aiohttp`` application
(WS, GET, POST and MCP handlers registered directly) served by
``aiohttp.test_utils.TestServer`` / ``TestClient`` inside an
``unittest.IsolatedAsyncioTestCase``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time
import types
import unittest
from pathlib import Path
from typing import Any

from aiohttp import test_utils, web

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ROOT_MODULE_NAME = "_comfyui_ai_assistant_write_test"

_POST_HEADERS = {"Content-Type": "application/json"}

ROOT_MOD = None
SERVER_MOD = None


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


def _snapshot(*, revision: int, widgets: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    selection: list[dict[str, Any]] = []
    if widgets is not None:
        selection = [{"id": 3, "title": "KSampler", "widgets": widgets}]
    return {
        "schema_version": "comfyui.ai-assistant.context/1",
        "captured_at": "2026-08-29T10:00:00+00:00",
        "revision": revision,
        "workflow": {
            "id": 3,
            "title": "KSampler",
            "selection_detail": "full",
            "selected_count": 1 if widgets else 0,
        },
        "selection": selection,
    }


def _text_snapshot(revision: int, text: str = "old") -> dict[str, Any]:
    return _snapshot(revision=revision, widgets=[{"name": "prompt", "type": "text", "value": text}])


def _mixed_snapshot(revision: int) -> dict[str, Any]:
    return _snapshot(
        revision=revision,
        widgets=[
            {"name": "prompt", "type": "text", "value": "old"},
            {"name": "cfg", "type": "number", "value": 1},
        ],
    )


def _set_widget_call_args(arguments: Any, id_value: str = "write-1") -> bytes:
    message = {
        "jsonrpc": "2.0",
        "id": id_value,
        "method": "tools/call",
        "params": {"name": "set_widget_text", "arguments": arguments},
    }
    return json.dumps(message).encode("utf-8")


def _set_widget_call(widget: str, text: str, expected_revision: int) -> bytes:
    return _set_widget_call_args(
        {"widget": widget, "text": text, "expected_revision": expected_revision}
    )


def _get_selection_call() -> bytes:
    message = {
        "jsonrpc": "2.0",
        "id": "sel-1",
        "method": "tools/call",
        "params": {"name": "get_selection"},
    }
    return json.dumps(message).encode("utf-8")


class WritePathTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        SERVER_MOD._mailbox = SERVER_MOD.ContextMailbox()
        SERVER_MOD._registry = SERVER_MOD.PageRegistry()
        SERVER_MOD._mailbox_mirrored_page = None
        SERVER_MOD._page_sockets = {}
        SERVER_MOD._pending_write = None

    async def asyncSetUp(self) -> None:
        app = web.Application()
        app.router.add_get(SERVER_MOD.CONTEXT_PATH, SERVER_MOD.handle_get)
        app.router.add_post(SERVER_MOD.CONTEXT_PATH, SERVER_MOD.handle_post)
        app.router.add_get(SERVER_MOD.WS_PATH, SERVER_MOD.handle_ws)
        app.router.add_route("*", SERVER_MOD.MCP_PATH, SERVER_MOD.handle_mcp)
        self.server = test_utils.TestServer(app)
        await self.server.start_server()
        self.client = test_utils.TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        await self.server.close()

    async def _connect_ws(self):
        return await self.client.ws_connect(SERVER_MOD.WS_PATH)

    async def _register(self, ws, page_id: str) -> None:
        await ws.send_json({"type": "register", "page_id": page_id})
        reply = await ws.receive_json()
        self.assertEqual(reply, {"type": "registered", "ok": True})

    async def _send_snapshot(self, ws, page_id: str, snapshot: dict[str, Any]) -> None:
        await ws.send_json({"type": "snapshot", "page_id": page_id, "snapshot": snapshot})
        reply = await ws.receive_json()
        self.assertEqual(reply, {"type": "accepted", "ok": True, "revision": snapshot["revision"]})

    async def _post_mcp(self, body: bytes):
        response = await self.client.post(SERVER_MOD.MCP_PATH, data=body, headers=_POST_HEADERS)
        self.assertEqual(response.status, 200)
        return await response.json()

    async def _wait_until(self, predicate, timeout: float = 1.0) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if predicate():
                return
            await asyncio.sleep(0.01)
        raise AssertionError("condition not met within timeout")

    async def test_invalid_params_refused_without_page(self):
        for arguments in (
            {"widget": "prompt", "text": "new"},
            {"widget": "prompt", "expected_revision": 7},
            {"widget": "prompt", "text": "new", "expected_revision": 7, "extra": 1},
            {"widget": 3, "text": "new", "expected_revision": 7},
            "not-a-dict",
        ):
            with self.subTest(arguments=arguments):
                body = await self._post_mcp(_set_widget_call_args(arguments))
                result = body["result"]
                self.assertIs(result["isError"], True)
                self.assertTrue(json.loads(result["content"][0]["text"])["error"])

    async def test_no_selection_refused(self):
        body = await self._post_mcp(_set_widget_call("prompt", "new", 7))
        result = body["result"]
        self.assertIs(result["isError"], True)
        self.assertEqual(
            json.loads(result["content"][0]["text"])["error"],
            "no selection available",
        )

    async def test_revision_mismatch_carries_current_revision(self):
        ws = await self._connect_ws()
        try:
            await self._register(ws, "tab-a")
            await self._send_snapshot(ws, "tab-a", _text_snapshot(7))
            body = await self._post_mcp(_set_widget_call("prompt", "new", 5))
            result = body["result"]
            self.assertIs(result["isError"], True)
            payload = json.loads(result["content"][0]["text"])
            self.assertEqual(payload["error"], "revision mismatch")
            self.assertEqual(payload["current_revision"], 7)
        finally:
            await ws.close()

    async def test_unknown_widget_and_not_text_like_refused(self):
        ws = await self._connect_ws()
        try:
            await self._register(ws, "tab-a")
            await self._send_snapshot(ws, "tab-a", _mixed_snapshot(7))
            for widget, expected_error in (
                ("missing", "unknown widget"),
                ("cfg", "widget is not text-like"),
            ):
                with self.subTest(widget=widget):
                    body = await self._post_mcp(_set_widget_call(widget, "new", 7))
                    result = body["result"]
                    self.assertIs(result["isError"], True)
                    self.assertEqual(
                        json.loads(result["content"][0]["text"])["error"],
                        expected_error,
                    )
        finally:
            await ws.close()

    async def test_no_active_page_with_closed_socket(self):
        ws = await self._connect_ws()
        await self._register(ws, "tab-a")
        await self._send_snapshot(ws, "tab-a", _text_snapshot(7))
        await ws.close()
        await self._wait_until(
            lambda: SERVER_MOD._registry.active_page_id() is None and not SERVER_MOD._page_sockets
        )
        body = await self._post_mcp(_set_widget_call("prompt", "new", 7))
        result = body["result"]
        self.assertIs(result["isError"], True)
        self.assertEqual(json.loads(result["content"][0]["text"])["error"], "no active page")

    async def test_happy_path_applied_on_revision_advance(self):
        ws = await self._connect_ws()
        try:
            await self._register(ws, "tab-a")
            await self._send_snapshot(ws, "tab-a", _text_snapshot(7))
            mcp_task = asyncio.create_task(
                self.client.post(
                    SERVER_MOD.MCP_PATH,
                    data=_set_widget_call("prompt", "new", 7),
                    headers=_POST_HEADERS,
                )
            )
            frame = await ws.receive_json()
            self.assertEqual(frame["type"], "command")
            self.assertEqual(frame["op"], "set_widget_text")
            self.assertEqual(frame["widget"], "prompt")
            self.assertEqual(frame["text"], "new")
            self.assertIsInstance(frame["command_id"], str)
            self.assertTrue(frame["command_id"])
            await self._send_snapshot(ws, "tab-a", _text_snapshot(8, text="new"))
            response = await mcp_task
            self.assertEqual(response.status, 200)
            body = await response.json()
            result = body["result"]
            self.assertIs(result["isError"], False)
            self.assertEqual(
                json.loads(result["content"][0]["text"]),
                {"status": "applied", "revision": 8, "widget": "prompt"},
            )
            self.assertIsNone(SERVER_MOD._pending_write)
        finally:
            await ws.close()

    async def test_queued_when_page_never_confirms(self):
        original = SERVER_MOD.WRITE_CONFIRM_TIMEOUT
        SERVER_MOD.WRITE_CONFIRM_TIMEOUT = 0.3
        try:
            ws = await self._connect_ws()
            try:
                await self._register(ws, "tab-a")
                await self._send_snapshot(ws, "tab-a", _text_snapshot(7))
                started = time.monotonic()
                mcp_task = asyncio.create_task(
                    self.client.post(
                        SERVER_MOD.MCP_PATH,
                        data=_set_widget_call("prompt", "new", 7),
                        headers=_POST_HEADERS,
                    )
                )
                frame = await ws.receive_json()
                self.assertEqual(frame["type"], "command")
                self.assertEqual(frame["op"], "set_widget_text")
                response = await mcp_task
                elapsed = time.monotonic() - started
                self.assertEqual(response.status, 200)
                body = await response.json()
                result = body["result"]
                self.assertIs(result["isError"], False)
                self.assertEqual(
                    json.loads(result["content"][0]["text"]),
                    {"status": "queued", "revision": 7, "widget": "prompt"},
                )
                self.assertLess(elapsed, 2.0)
                self.assertIsNone(SERVER_MOD._pending_write)
            finally:
                await ws.close()
        finally:
            SERVER_MOD.WRITE_CONFIRM_TIMEOUT = original

    async def test_get_selection_still_served_by_same_app(self):
        ws = await self._connect_ws()
        try:
            await self._register(ws, "tab-a")
            await self._send_snapshot(ws, "tab-a", _text_snapshot(7))
            body = await self._post_mcp(_get_selection_call())
            result = body["result"]
            self.assertIs(result["isError"], False)
            envelope = json.loads(result["content"][0]["text"])
            self.assertIs(envelope["available"], True)
            self.assertEqual(envelope["snapshot"]["revision"], 7)
            self.assertEqual(
                envelope["active_page"],
                {"page_id": "tab-a", "connected": True},
            )
        finally:
            await ws.close()


if __name__ == "__main__":
    unittest.main()
