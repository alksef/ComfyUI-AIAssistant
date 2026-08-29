"""Isolated contract tests for the ComfyUI-AIAssistant backend extension.

A minimal fake ``server`` module stands in for ComfyUI's before the repository
root ``__init__.py`` is loaded the way ComfyUI loads it, so the tests require no
running ComfyUI process.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ROOT_MODULE_NAME = "_comfyui_ai_assistant_plugin_test"


class FakeContent:
    def __init__(self, data: bytes, declared_length: int | None = None) -> None:
        self._data = data
        self._declared_length = declared_length

    async def iter_chunked(self, chunk_size: int):
        data = self._data
        for start in range(0, len(data), chunk_size):
            yield data[start : start + chunk_size]


class FakeRequest:
    def __init__(
        self,
        body: bytes = b"",
        declared_length: int | None = None,
        method: str = "POST",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.content = FakeContent(body, declared_length)
        self.content_length = declared_length
        self.method = method
        self.headers = headers if headers is not None else {"Content-Type": "application/json"}


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


ROOT_MOD = None
SERVER_MOD = None


def _load_root_entrypoint():
    path = _REPO_ROOT / "__init__.py"
    spec = importlib.util.spec_from_file_location(_ROOT_MODULE_NAME, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[_ROOT_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def setUpModule() -> None:
    fake_server = types.ModuleType("server")
    fake_server.PromptServer = FakePromptServer
    FakePromptServer.instance = FakePromptServer()
    sys.modules["server"] = fake_server

    global ROOT_MOD, SERVER_MOD, MCP_MOD
    if "ai_assistant" in sys.modules:
        raise AssertionError("test isolation requires no top-level ai_assistant module")
    ROOT_MOD = _load_root_entrypoint()
    SERVER_MOD = sys.modules[f"{_ROOT_MODULE_NAME}.ai_assistant.server"]
    MCP_MOD = sys.modules[f"{_ROOT_MODULE_NAME}.ai_assistant.mcp_protocol"]


def _valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "comfyui.ai-assistant.context/1",
        "captured_at": "2026-08-29T10:00:00+00:00",
        "revision": 7,
        "workflow": {"id": 3, "title": "KSampler"},
        "selection": [{"id": 3, "title": "KSampler"}],
        "extra_top_level": "dropped",
    }
    payload.update(overrides)
    return payload


def _valid_body(**overrides: object) -> bytes:
    return json.dumps(_valid_payload(**overrides)).encode("utf-8")


async def _post(body: bytes, declared_length: int | None = None):
    request = FakeRequest(body, declared_length)
    return await SERVER_MOD.handle_post(request)


async def _get():
    return await SERVER_MOD.handle_get(FakeRequest())


async def _mcp(
    body: bytes = b"",
    *,
    method: str = "POST",
    declared_length: int | None = None,
    content_type: str = "application/json",
):
    request = FakeRequest(
        body,
        declared_length,
        method=method,
        headers={"Content-Type": content_type},
    )
    return await SERVER_MOD.handle_mcp(request)


class RootEntrypointTests(unittest.TestCase):
    def test_does_not_create_top_level_backend_package(self):
        self.assertNotIn("ai_assistant", sys.modules)

    def test_exposes_standard_extension_constants(self):
        self.assertEqual(ROOT_MOD.WEB_DIRECTORY, "./web")
        self.assertEqual(ROOT_MOD.NODE_CLASS_MAPPINGS, {})
        self.assertEqual(ROOT_MOD.NODE_DISPLAY_NAME_MAPPINGS, {})

    def test_registers_context_mcp_and_ws_routes(self):
        registered = FakePromptServer.instance.routes.routes
        context_routes = [(m, p) for m, p, _h in registered if p == SERVER_MOD.CONTEXT_PATH]
        mcp_routes = [(m, p) for m, p, _h in registered if p == SERVER_MOD.MCP_PATH]
        ws_routes = [(m, p) for m, p, _h in registered if p == SERVER_MOD.WS_PATH]
        self.assertEqual(len(registered), 4)
        self.assertEqual(sorted(m for m, _p in context_routes), ["GET", "POST"])
        self.assertEqual(mcp_routes, [("*", SERVER_MOD.MCP_PATH)])
        self.assertEqual(ws_routes, [("GET", SERVER_MOD.WS_PATH)])

    def test_registered_handlers_are_the_backend_handlers(self):
        handlers = {(m, p): h for m, p, h in FakePromptServer.instance.routes.routes}
        self.assertIs(handlers[("GET", SERVER_MOD.CONTEXT_PATH)], SERVER_MOD.handle_get)
        self.assertIs(handlers[("POST", SERVER_MOD.CONTEXT_PATH)], SERVER_MOD.handle_post)
        self.assertIs(handlers[("*", SERVER_MOD.MCP_PATH)], SERVER_MOD.handle_mcp)
        self.assertIs(handlers[("GET", SERVER_MOD.WS_PATH)], SERVER_MOD.handle_ws)


class ContextMailboxTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        SERVER_MOD._mailbox = SERVER_MOD.ContextMailbox()

    @staticmethod
    def _json(response) -> dict[str, object]:
        return json.loads(response.body)

    def _assert_no_store(self, response) -> None:
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")

    async def test_initial_get_returns_deterministic_unavailable_envelope(self):
        response = await _get()
        self.assertEqual(response.status, 200)
        self._assert_no_store(response)
        body = self._json(response)
        self.assertEqual(body["schema_version"], "comfyui.ai-assistant.context/1")
        self.assertIs(body["available"], False)
        self.assertIsNone(body["received_at"])
        self.assertIsNone(body["snapshot"])
        self.assertEqual(body["pages"], [])
        self.assertIsNone(body["active_page"])

    async def test_valid_post_then_get_returns_normalized_snapshot(self):
        post_response = await _post(_valid_body())
        self.assertEqual(post_response.status, 200)
        self._assert_no_store(post_response)
        ack = self._json(post_response)
        self.assertIs(ack["accepted"], True)
        self.assertEqual(ack["revision"], 7)

        get_response = await _get()
        self.assertEqual(get_response.status, 200)
        self._assert_no_store(get_response)
        body = self._json(get_response)
        self.assertIs(body["available"], True)
        self.assertIsInstance(body["received_at"], str)
        self.assertIsNotNone(body["snapshot"])
        snapshot = body["snapshot"]
        self.assertEqual(
            set(snapshot.keys()),
            {"schema_version", "captured_at", "revision", "workflow", "selection"},
        )
        self.assertEqual(snapshot["schema_version"], "comfyui.ai-assistant.context/1")
        self.assertEqual(snapshot["captured_at"], "2026-08-29T10:00:00+00:00")
        self.assertEqual(snapshot["revision"], 7)
        self.assertEqual(snapshot["workflow"], {"id": 3, "title": "KSampler"})
        self.assertEqual(snapshot["selection"], [{"id": 3, "title": "KSampler"}])
        self.assertEqual(body["pages"], [])
        self.assertIsNone(body["active_page"])

    async def test_empty_selection_is_available(self):
        response = await _post(_valid_body(selection=[]))
        self.assertEqual(response.status, 200)
        body = self._json(await _get())
        self.assertIs(body["available"], True)
        self.assertEqual(body["snapshot"]["selection"], [])

    async def test_revision_zero_is_accepted(self):
        response = await _post(_valid_body(revision=0))
        self.assertEqual(response.status, 200)
        self.assertEqual(self._json(response)["revision"], 0)

    async def test_workflow_null_is_accepted(self):
        response = await _post(_valid_body(workflow=None))
        self.assertEqual(response.status, 200)
        self.assertIsNone(self._json(await _get())["snapshot"]["workflow"])

    async def test_unknown_top_level_keys_are_not_retained(self):
        await _post(_valid_body())
        snapshot = self._json(await _get())["snapshot"]
        self.assertNotIn("extra_top_level", snapshot)

    async def test_malformed_json_is_rejected(self):
        response = await _post(b"{not json")
        self.assertEqual(response.status, 400)
        self.assertEqual(set(self._json(response).keys()), {"error"})

    async def test_non_object_body_is_rejected(self):
        for raw in (b"[1, 2]", b'"text"', b"42", b"true", b"null"):
            response = await _post(raw)
            self.assertEqual(response.status, 400)
            self.assertEqual(set(self._json(response).keys()), {"error"})

    async def test_wrong_schema_version_is_rejected(self):
        payload = _valid_payload(schema_version="comfyui.ai-assistant.context/2")
        response = await _post(json.dumps(payload).encode("utf-8"))
        self.assertEqual(response.status, 400)

    async def test_missing_required_fields_are_rejected(self):
        for key in ("schema_version", "captured_at", "revision", "selection"):
            payload = _valid_payload()
            del payload[key]
            response = await _post(json.dumps(payload).encode("utf-8"))
            self.assertEqual(response.status, 400)

    async def test_empty_captured_at_is_rejected(self):
        response = await _post(_valid_body(captured_at=""))
        self.assertEqual(response.status, 400)

    async def test_negative_revision_is_rejected(self):
        response = await _post(_valid_body(revision=-1))
        self.assertEqual(response.status, 400)

    async def test_boolean_revision_is_rejected(self):
        for value in (True, False):
            response = await _post(_valid_body(revision=value))
            self.assertEqual(response.status, 400)

    async def test_workflow_that_is_not_object_or_null_is_rejected(self):
        for value in ("workflow", 3, True, [1]):
            response = await _post(_valid_body(workflow=value))
            self.assertEqual(response.status, 400)

    async def test_selection_that_is_not_an_array_is_rejected(self):
        for value in ("selection", 3, True, {"id": 3}):
            response = await _post(_valid_body(selection=value))
            self.assertEqual(response.status, 400)

    async def test_declared_content_length_over_limit_is_rejected(self):
        response = await _post(_valid_body(), declared_length=SERVER_MOD.MAX_BODY_BYTES + 1)
        self.assertEqual(response.status, 413)
        self.assertEqual(set(self._json(response).keys()), {"error"})

    async def test_actual_bytes_over_limit_are_rejected(self):
        response = await _post(b"x" * (SERVER_MOD.MAX_BODY_BYTES + 1))
        self.assertEqual(response.status, 413)

    async def test_lying_declared_length_does_not_bypass_limit(self):
        response = await _post(
            b"x" * (SERVER_MOD.MAX_BODY_BYTES + 1),
            declared_length=1,
        )
        self.assertEqual(response.status, 413)

    async def test_rejected_post_preserves_previous_snapshot(self):
        await _post(_valid_body(revision=5))
        await _post(b"{not json")
        body = self._json(await _get())
        self.assertEqual(body["snapshot"]["revision"], 5)

    async def test_oversized_post_preserves_previous_snapshot(self):
        await _post(_valid_body(revision=2))
        response = await _post(b"x" * (SERVER_MOD.MAX_BODY_BYTES + 1))
        self.assertEqual(response.status, 413)
        body = self._json(await _get())
        self.assertEqual(body["snapshot"]["revision"], 2)

    async def test_no_store_header_on_every_response(self):
        responses = [
            await _get(),
            await _post(_valid_body()),
            await _post(b"{not json"),
            await _post(b"x" * (SERVER_MOD.MAX_BODY_BYTES + 1)),
        ]
        for response in responses:
            self._assert_no_store(response)

    async def test_returned_snapshot_is_not_mutable_through_caller(self):
        await _post(_valid_body())
        snapshot = self._json(await _get())["snapshot"]
        snapshot["selection"].append("mutated")
        snapshot["workflow"]["id"] = 999
        fresh = self._json(await _get())["snapshot"]
        self.assertEqual(fresh["selection"], [{"id": 3, "title": "KSampler"}])
        self.assertEqual(fresh["workflow"]["id"], 3)


class McpRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        SERVER_MOD._mailbox = SERVER_MOD.ContextMailbox()

    @staticmethod
    def _json(response) -> dict[str, object]:
        return json.loads(response.body)

    def _assert_no_store(self, response) -> None:
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")

    @staticmethod
    def _message(method: str, *, id_value: object = "1", params: object = None) -> bytes:
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if id_value is not None:
            message["id"] = id_value
        return json.dumps(message).encode("utf-8")

    async def test_initialize_over_http_returns_200_json(self):
        message = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "init-1",
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            }
        ).encode("utf-8")
        response = await _mcp(message)
        self.assertEqual(response.status, 200)
        self._assert_no_store(response)
        body = self._json(response)
        self.assertEqual(body["id"], "init-1")
        self.assertNotIn("error", body)
        self.assertEqual(body["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(body["result"]["capabilities"], {"tools": {"listChanged": False}})

    async def test_notification_returns_202_with_empty_body(self):
        response = await _mcp(self._message("notifications/initialized", id_value=None))
        self.assertEqual(response.status, 202)
        self._assert_no_store(response)
        self.assertIsNone(response.body)

    async def test_tools_list_returns_200_json(self):
        response = await _mcp(self._message("tools/list"))
        self.assertEqual(response.status, 200)
        self._assert_no_store(response)
        tools = self._json(response)["result"]["tools"]
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], MCP_MOD.TOOL_NAME)

    async def test_tools_call_unavailable_envelope_when_mailbox_empty(self):
        response = await _mcp(self._message("tools/call", params={"name": MCP_MOD.TOOL_NAME}))
        self.assertEqual(response.status, 200)
        self._assert_no_store(response)
        body = self._json(response)
        self.assertIs(body["result"]["isError"], False)
        envelope = json.loads(body["result"]["content"][0]["text"])
        self.assertEqual(envelope["schema_version"], SERVER_MOD.SCHEMA_VERSION)
        self.assertIs(envelope["available"], False)
        self.assertIsNone(envelope["received_at"])
        self.assertIsNone(envelope["snapshot"])
        self.assertEqual(envelope["pages"], [])
        self.assertIsNone(envelope["active_page"])

    async def test_tools_call_reads_live_mailbox_state(self):
        await _post(_valid_body())
        response = await _mcp(self._message("tools/call", params={"name": MCP_MOD.TOOL_NAME}))
        self.assertEqual(response.status, 200)
        body = self._json(response)
        self.assertIs(body["result"]["isError"], False)
        envelope = json.loads(body["result"]["content"][0]["text"])
        self.assertIs(envelope["available"], True)
        self.assertIsInstance(envelope["received_at"], str)
        self.assertEqual(envelope["snapshot"]["revision"], 7)
        self.assertEqual(envelope["snapshot"]["selection"], [{"id": 3, "title": "KSampler"}])
        self.assertEqual(envelope["pages"], [])
        self.assertIsNone(envelope["active_page"])

    async def test_mcp_envelope_matches_get_route_body(self):
        await _post(_valid_body())
        get_body = self._json(await _get())
        response = await _mcp(self._message("tools/call", params={"name": MCP_MOD.TOOL_NAME}))
        envelope = json.loads(self._json(response)["result"]["content"][0]["text"])
        self.assertEqual(envelope, get_body)

    async def test_ping_returns_200_json(self):
        response = await _mcp(self._message("ping", id_value=5))
        self.assertEqual(response.status, 200)
        self.assertEqual(self._json(response)["result"], {})

    async def test_unknown_method_returns_method_not_found(self):
        response = await _mcp(self._message("bogus/method"))
        self.assertEqual(response.status, 200)
        body = self._json(response)
        self.assertEqual(body["id"], "1")
        self.assertEqual(body["error"]["code"], MCP_MOD.METHOD_NOT_FOUND)

    async def test_id_round_trips_over_http(self):
        response = await _mcp(self._message("ping", id_value="abc-123"))
        self.assertEqual(self._json(response)["id"], "abc-123")

    async def test_oversized_body_returns_413(self):
        response = await _mcp(b"x" * (SERVER_MOD.MAX_MCP_BODY_BYTES + 1))
        self.assertEqual(response.status, 413)
        self._assert_no_store(response)

    async def test_declared_length_over_limit_returns_413(self):
        response = await _mcp(b"{}", declared_length=SERVER_MOD.MAX_MCP_BODY_BYTES + 1)
        self.assertEqual(response.status, 413)

    async def test_oversized_notification_never_reaches_dispatcher(self):
        message = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        big = message.encode("utf-8") + b" " * SERVER_MOD.MAX_MCP_BODY_BYTES
        response = await _mcp(big)
        self.assertEqual(response.status, 413)
        self.assertEqual(response.body, b"request body too large")

    async def test_wrong_content_type_returns_415(self):
        for content_type in ("text/plain", "", "application/x-www-form-urlencoded"):
            with self.subTest(content_type=content_type):
                response = await _mcp(b"{}", content_type=content_type)
                self.assertEqual(response.status, 415)
                self._assert_no_store(response)

    async def test_charset_suffix_content_type_is_accepted(self):
        response = await _mcp(b"{}", content_type="application/json; charset=utf-8")
        self.assertEqual(response.status, 200)

    async def test_get_and_delete_return_405_with_allow_post(self):
        for method in ("GET", "DELETE"):
            with self.subTest(method=method):
                response = await _mcp(method=method)
                self.assertEqual(response.status, 405)
                self.assertEqual(response.headers.get("Allow"), "POST")
                self._assert_no_store(response)

    async def test_invalid_json_returns_parse_error_in_band(self):
        for raw in (b"{not json", b"\xff\xfe\x00", b""):
            with self.subTest(raw=raw):
                response = await _mcp(raw)
                self.assertEqual(response.status, 200)
                self._assert_no_store(response)
                body = self._json(response)
                self.assertEqual(body["jsonrpc"], "2.0")
                self.assertIsNone(body["id"])
                self.assertEqual(body["error"]["code"], MCP_MOD.PARSE_ERROR)

    async def test_no_store_on_every_mcp_response_class(self):
        responses = [
            await _mcp(self._message("ping")),
            await _mcp(self._message("notifications/initialized", id_value=None)),
            await _mcp(b"{not json"),
            await _mcp(b"x" * (SERVER_MOD.MAX_MCP_BODY_BYTES + 1)),
            await _mcp(method="GET"),
            await _mcp(content_type="text/plain"),
        ]
        for response in responses:
            self._assert_no_store(response)


if __name__ == "__main__":
    unittest.main()
