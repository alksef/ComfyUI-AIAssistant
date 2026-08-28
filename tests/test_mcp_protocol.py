"""Contract tests for the pure MCP JSON-RPC dispatcher.

The module under test imports only the standard library, so it is loaded
directly by file path under a unique module name and requires no ComfyUI, fake
``server`` module, or aiohttp.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MODULE_NAME = "_ai_assistant_mcp_protocol_test"


def _load_module():
    path = _REPO_ROOT / "ai_assistant" / "mcp_protocol.py"
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


MCP = _load_module()

AVAILABLE_ENVELOPE: dict[str, Any] = {
    "schema_version": "comfyui.ai-assistant.context/1",
    "available": True,
    "received_at": "2026-08-29T10:00:00+00:00",
    "snapshot": {
        "schema_version": "comfyui.ai-assistant.context/1",
        "captured_at": "2026-08-29T10:00:00+00:00",
        "revision": 7,
        "workflow": {"id": 3, "title": "KSampler"},
        "selection": [{"id": 3, "title": "KSampler"}],
    },
}

UNAVAILABLE_ENVELOPE: dict[str, Any] = {
    "schema_version": "comfyui.ai-assistant.context/1",
    "available": False,
    "received_at": None,
    "snapshot": None,
}


def _provider(envelope: dict[str, Any]):
    return lambda: envelope


def _message(
    method: str,
    *,
    id_value: Any = "1",
    params: Any = None,
    include_params: bool = False,
) -> dict[str, Any]:
    message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if include_params:
        message["params"] = params
    if id_value is not _NO_ID:
        message["id"] = id_value
    return message


class _NoId:
    pass


_NO_ID = _NoId()


class InitializeTests(unittest.TestCase):
    def test_echoes_client_protocol_version(self):
        response = MCP.dispatch(
            _message(
                "initialize",
                params={"protocolVersion": "2025-03-26"},
                include_params=True,
            ),
            _provider({}),
        )
        self.assertEqual(response["result"]["protocolVersion"], "2025-03-26")

    def test_reports_minimal_capabilities(self):
        response = MCP.dispatch(_message("initialize"), _provider({}))
        self.assertEqual(response["result"]["capabilities"], {"tools": {"listChanged": False}})

    def test_reports_server_info_from_constants(self):
        response = MCP.dispatch(_message("initialize"), _provider({}))
        self.assertEqual(
            response["result"]["serverInfo"],
            {"name": MCP.SERVER_NAME, "version": MCP.SERVER_VERSION},
        )

    def test_default_protocol_version_without_params(self):
        response = MCP.dispatch(_message("initialize"), _provider({}))
        self.assertEqual(response["result"]["protocolVersion"], MCP.DEFAULT_PROTOCOL_VERSION)

    def test_default_protocol_version_when_protocol_missing(self):
        response = MCP.dispatch(_message("initialize", params={"clientInfo": {}}), _provider({}))
        self.assertEqual(response["result"]["protocolVersion"], MCP.DEFAULT_PROTOCOL_VERSION)

    def test_default_protocol_version_when_protocol_not_string(self):
        for value in (3, None, True, []):
            with self.subTest(value=value):
                response = MCP.dispatch(
                    _message("initialize", params={"protocolVersion": value}),
                    _provider({}),
                )
                self.assertEqual(
                    response["result"]["protocolVersion"], MCP.DEFAULT_PROTOCOL_VERSION
                )

    def test_non_object_params_get_invalid_params(self):
        for params in ("x", 3, [1], True):
            with self.subTest(params=params):
                response = MCP.dispatch(
                    _message("initialize", params=params, include_params=True),
                    _provider({}),
                )
                self.assertEqual(response["error"]["code"], MCP.INVALID_PARAMS)
                self.assertNotIn("result", response)


class NotificationTests(unittest.TestCase):
    def test_notifications_initialized_produces_no_response(self):
        response = MCP.dispatch(
            _message("notifications/initialized", id_value=_NO_ID), _provider({})
        )
        self.assertIsNone(response)

    def test_unknown_notification_produces_no_response(self):
        response = MCP.dispatch(_message("bogus/method", id_value=_NO_ID), _provider({}))
        self.assertIsNone(response)

    def test_known_method_as_notification_produces_no_response(self):
        response = MCP.dispatch(_message("ping", id_value=_NO_ID), _provider({}))
        self.assertIsNone(response)


class ToolsListTests(unittest.TestCase):
    def test_returns_exactly_one_tool_with_exact_shape(self):
        response = MCP.dispatch(_message("tools/list", id_value="list-1"), _provider({}))
        self.assertEqual(response["id"], "list-1")
        self.assertNotIn("error", response)
        tools = response["result"]["tools"]
        self.assertEqual(len(tools), 1)
        tool = tools[0]
        self.assertEqual(tool["name"], MCP.TOOL_NAME)
        self.assertEqual(tool["description"], MCP.TOOL_DESCRIPTION)
        self.assertEqual(
            tool["inputSchema"],
            {"type": "object", "properties": {}, "additionalProperties": False},
        )
        self.assertNotIn("\n", tool["description"])

    def test_accepts_absent_params(self):
        response = MCP.dispatch(_message("tools/list"), _provider({}))
        self.assertEqual(response["result"]["tools"][0]["name"], MCP.TOOL_NAME)

    def test_non_object_params_get_invalid_params(self):
        response = MCP.dispatch(
            _message("tools/list", params="x", include_params=True), _provider({})
        )
        self.assertEqual(response["error"]["code"], MCP.INVALID_PARAMS)


class ToolsCallTests(unittest.TestCase):
    def test_available_envelope_passthrough(self):
        response = MCP.dispatch(
            _message("tools/call", params={"name": MCP.TOOL_NAME}, include_params=True),
            _provider(AVAILABLE_ENVELOPE),
        )
        self.assertIs(response["result"]["isError"], False)
        content = response["result"]["content"]
        self.assertEqual(content[0]["type"], "text")
        self.assertEqual(
            content[0]["text"],
            json.dumps(AVAILABLE_ENVELOPE, separators=(",", ":")),
        )

    def test_unavailable_envelope_passthrough(self):
        response = MCP.dispatch(
            _message("tools/call", params={"name": MCP.TOOL_NAME}, include_params=True),
            _provider(UNAVAILABLE_ENVELOPE),
        )
        self.assertEqual(
            response["result"]["content"][0]["text"],
            json.dumps(UNAVAILABLE_ENVELOPE, separators=(",", ":")),
        )

    def test_empty_arguments_are_accepted(self):
        response = MCP.dispatch(
            _message(
                "tools/call",
                params={"name": MCP.TOOL_NAME, "arguments": {}},
                include_params=True,
            ),
            _provider(AVAILABLE_ENVELOPE),
        )
        self.assertNotIn("error", response)

    def test_unknown_tool_name_get_invalid_params(self):
        response = MCP.dispatch(
            _message("tools/call", params={"name": "other"}, include_params=True),
            _provider({}),
        )
        self.assertEqual(response["error"]["code"], MCP.INVALID_PARAMS)
        self.assertEqual(response["id"], "1")

    def test_missing_params_get_invalid_params(self):
        response = MCP.dispatch(_message("tools/call"), _provider({}))
        self.assertEqual(response["error"]["code"], MCP.INVALID_PARAMS)

    def test_non_object_params_get_invalid_params(self):
        for params in ("x", [1], True):
            with self.subTest(params=params):
                response = MCP.dispatch(
                    _message("tools/call", params=params, include_params=True),
                    _provider({}),
                )
                self.assertEqual(response["error"]["code"], MCP.INVALID_PARAMS)

    def test_missing_name_get_invalid_params(self):
        response = MCP.dispatch(
            _message("tools/call", params={}, include_params=True), _provider({})
        )
        self.assertEqual(response["error"]["code"], MCP.INVALID_PARAMS)

    def test_non_string_name_get_invalid_params(self):
        for name in (3, None, True, ["x"]):
            with self.subTest(name=name):
                response = MCP.dispatch(
                    _message("tools/call", params={"name": name}, include_params=True),
                    _provider({}),
                )
                self.assertEqual(response["error"]["code"], MCP.INVALID_PARAMS)

    def test_non_empty_arguments_get_invalid_params(self):
        for arguments in ({"x": 1}, [], "x", 3, None):
            with self.subTest(arguments=arguments):
                response = MCP.dispatch(
                    _message(
                        "tools/call",
                        params={"name": MCP.TOOL_NAME, "arguments": arguments},
                        include_params=True,
                    ),
                    _provider({}),
                )
                self.assertEqual(response["error"]["code"], MCP.INVALID_PARAMS)

    def test_extra_params_get_invalid_params(self):
        response = MCP.dispatch(
            _message(
                "tools/call",
                params={"name": MCP.TOOL_NAME, "extra": 1},
                include_params=True,
            ),
            _provider({}),
        )
        self.assertEqual(response["error"]["code"], MCP.INVALID_PARAMS)


class PingTests(unittest.TestCase):
    def test_returns_empty_result(self):
        response = MCP.dispatch(_message("ping"), _provider({}))
        self.assertEqual(response["result"], {})
        self.assertNotIn("error", response)

    def test_accepts_absent_params(self):
        response = MCP.dispatch(_message("ping", id_value=0), _provider({}))
        self.assertEqual(response["result"], {})

    def test_non_object_params_get_invalid_params(self):
        response = MCP.dispatch(_message("ping", params="x", include_params=True), _provider({}))
        self.assertEqual(response["error"]["code"], MCP.INVALID_PARAMS)


class UnknownMethodTests(unittest.TestCase):
    def test_unknown_method_get_method_not_found(self):
        response = MCP.dispatch(_message("tools/not-real", id_value="nope"), _provider({}))
        self.assertEqual(response["error"]["code"], MCP.METHOD_NOT_FOUND)
        self.assertEqual(response["id"], "nope")
        self.assertNotIn("result", response)


class InvalidRequestTests(unittest.TestCase):
    def test_non_object_body_get_invalid_request(self):
        for body in ([1, 2], "text", 42, True, None):
            with self.subTest(body=body):
                response = MCP.dispatch(body, _provider({}))
                self.assertEqual(response["error"]["code"], MCP.INVALID_REQUEST)
                self.assertIsNone(response["id"])
                self.assertNotIn("result", response)

    def test_object_without_jsonrpc_get_invalid_request(self):
        response = MCP.dispatch({"method": "ping", "id": 1}, _provider({}))
        self.assertEqual(response["error"]["code"], MCP.INVALID_REQUEST)
        self.assertIsNone(response["id"])

    def test_wrong_jsonrpc_version_get_invalid_request(self):
        for version in ("1.0", 2.0, None):
            with self.subTest(version=version):
                response = MCP.dispatch(
                    {"jsonrpc": version, "method": "ping", "id": 1}, _provider({})
                )
                self.assertEqual(response["error"]["code"], MCP.INVALID_REQUEST)
                self.assertIsNone(response["id"])

    def test_missing_method_get_invalid_request(self):
        for message in ({}, {"jsonrpc": "2.0", "id": 1}):
            with self.subTest(message=message):
                response = MCP.dispatch(message, _provider({}))
                self.assertEqual(response["error"]["code"], MCP.INVALID_REQUEST)
                self.assertIsNone(response["id"])

    def test_empty_method_get_invalid_request(self):
        response = MCP.dispatch({"jsonrpc": "2.0", "method": "", "id": 1}, _provider({}))
        self.assertEqual(response["error"]["code"], MCP.INVALID_REQUEST)
        self.assertIsNone(response["id"])


class IdRoundTripTests(unittest.TestCase):
    def test_string_id_round_trips(self):
        response = MCP.dispatch(_message("ping", id_value="abc-123"), _provider({}))
        self.assertEqual(response["id"], "abc-123")

    def test_integer_id_round_trips(self):
        response = MCP.dispatch(_message("ping", id_value=42), _provider({}))
        self.assertEqual(response["id"], 42)
        self.assertIs(type(response["id"]), int)

    def test_zero_id_round_trips(self):
        response = MCP.dispatch(_message("ping", id_value=0), _provider({}))
        self.assertEqual(response["id"], 0)

    def test_float_id_round_trips(self):
        response = MCP.dispatch(_message("ping", id_value=3.14), _provider({}))
        self.assertEqual(response["id"], 3.14)
        self.assertIs(type(response["id"]), float)

    def test_null_id_is_a_response_not_a_notification(self):
        response = MCP.dispatch(_message("ping", id_value=None), _provider({}))
        self.assertIsNotNone(response)
        self.assertIsNone(response["id"])
        self.assertEqual(response["result"], {})

    def test_error_response_echoes_id(self):
        response = MCP.dispatch(
            _message("ping", id_value=7, params="x", include_params=True),
            _provider({}),
        )
        self.assertEqual(response["id"], 7)
        self.assertEqual(response["error"]["code"], MCP.INVALID_PARAMS)


class ProviderIsolationTests(unittest.TestCase):
    def test_provider_not_called_for_non_tool_methods(self):
        calls: list[Any] = []

        def counting_provider():
            calls.append(1)
            return {}

        for message in (
            _message("initialize"),
            _message("tools/list"),
            _message("ping"),
            _message("unknown/method"),
            _message("notifications/initialized"),
        ):
            MCP.dispatch(message, counting_provider)
        self.assertEqual(calls, [])

    def test_provider_result_is_not_mutated_and_serializes_identically(self):
        envelope = dict(AVAILABLE_ENVELOPE)
        before = json.dumps(envelope, sort_keys=True)

        first = MCP.dispatch(
            _message("tools/call", params={"name": MCP.TOOL_NAME}, include_params=True),
            _provider(envelope),
        )
        second = MCP.dispatch(
            _message("tools/call", params={"name": MCP.TOOL_NAME}, include_params=True),
            _provider(envelope),
        )

        self.assertEqual(
            first["result"]["content"][0]["text"],
            second["result"]["content"][0]["text"],
        )
        self.assertEqual(json.dumps(envelope, sort_keys=True), before)


class RobustnessTests(unittest.TestCase):
    def test_dispatch_never_raises_for_json_decodable_inputs(self):
        providers = (_provider({}), _provider(AVAILABLE_ENVELOPE))
        decoded_values = (
            None,
            True,
            False,
            0,
            -1,
            3.5,
            "text",
            [],
            {},
            {"jsonrpc": "2.0", "method": "ping"},
            {"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 0},
            {"jsonrpc": "2.0", "method": "tools/call", "params": {}, "id": 1},
        )
        for value in decoded_values:
            for provider in providers:
                with self.subTest(value=value):
                    MCP.dispatch(value, provider)


if __name__ == "__main__":
    unittest.main()
