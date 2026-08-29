"""Pure JSON-RPC 2.0 dispatcher speaking a minimal MCP method set.

Framework-free by design: this module imports only the standard library and is
fully testable without ComfyUI, aiohttp or any third-party package. It turns a
decoded JSON-RPC message into a response object (or ``None`` for notifications)
and never logs, reads state, or touches the network; the enclosing transport
decides how to frame the result.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

JSONRPC_VERSION = "2.0"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"

SERVER_NAME = "comfyui-ai-assistant"
SERVER_VERSION = "0.1.0"

TOOL_NAME = "get_selection"
TOOL_DESCRIPTION = "Read-only access to the current ComfyUI canvas selection."

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

_ERROR_MESSAGES = {
    INVALID_REQUEST: "Invalid Request",
    METHOD_NOT_FOUND: "Method not found",
    INVALID_PARAMS: "Invalid params",
}

ContextProvider = Callable[[], Any]

__all__ = ["dispatch"]


def _error_response(id_value: Any, code: int) -> dict[str, Any]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": id_value,
        "error": {"code": code, "message": _ERROR_MESSAGES[code]},
    }


def _result_response(id_value: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": id_value, "result": result}


def _is_usable_message(message: dict[str, Any]) -> bool:
    method = message.get("method")
    return message.get("jsonrpc") == JSONRPC_VERSION and isinstance(method, str) and bool(method)


def _handle_initialize(id_value: Any, params: Any, has_params: bool) -> dict[str, Any]:
    if has_params and not isinstance(params, dict):
        return _error_response(id_value, INVALID_PARAMS)
    protocol_version = DEFAULT_PROTOCOL_VERSION
    if has_params:
        client_version = params.get("protocolVersion")
        if isinstance(client_version, str):
            protocol_version = client_version
    return _result_response(
        id_value,
        {
            "protocolVersion": protocol_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        },
    )


def _handle_tools_list(id_value: Any, params: Any, has_params: bool) -> dict[str, Any]:
    if has_params and not isinstance(params, dict):
        return _error_response(id_value, INVALID_PARAMS)
    return _result_response(
        id_value,
        {
            "tools": [
                {
                    "name": TOOL_NAME,
                    "description": TOOL_DESCRIPTION,
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                }
            ]
        },
    )


def _handle_tools_call(
    id_value: Any,
    params: Any,
    has_params: bool,
    context_provider: ContextProvider,
) -> dict[str, Any]:
    if not has_params or not isinstance(params, dict):
        return _error_response(id_value, INVALID_PARAMS)
    if params.get("name") != TOOL_NAME:
        return _error_response(id_value, INVALID_PARAMS)
    if set(params) - {"name", "arguments", "_meta"}:
        return _error_response(id_value, INVALID_PARAMS)
    if "_meta" in params and not isinstance(params["_meta"], dict):
        return _error_response(id_value, INVALID_PARAMS)
    arguments = params.get("arguments")
    if arguments is not None and arguments != {}:
        return _error_response(id_value, INVALID_PARAMS)
    envelope = context_provider()
    text = json.dumps(envelope, separators=(",", ":"))
    return _result_response(
        id_value,
        {"content": [{"type": "text", "text": text}], "isError": False},
    )


def _handle_ping(id_value: Any, params: Any, has_params: bool) -> dict[str, Any]:
    if has_params and not isinstance(params, dict):
        return _error_response(id_value, INVALID_PARAMS)
    return _result_response(id_value, {})


def dispatch(message: Any, context_provider: ContextProvider) -> dict[str, Any] | None:
    """Dispatch one decoded JSON-RPC message to a response dict or ``None``.

    ``message`` is the already-parsed JSON value. ``context_provider`` is a
    zero-argument callable returning the context envelope object; it is invoked
    only for a ``get_selection`` tool call and its return value is serialized
    without mutation. Notifications always yield ``None``.
    """
    if not isinstance(message, dict):
        return _error_response(None, INVALID_REQUEST)
    if not _is_usable_message(message):
        return _error_response(None, INVALID_REQUEST)
    if "id" not in message:
        return None

    id_value = message["id"]
    method = message["method"]
    has_params = "params" in message
    params = message.get("params")

    if method == "initialize":
        return _handle_initialize(id_value, params, has_params)
    if method == "tools/list":
        return _handle_tools_list(id_value, params, has_params)
    if method == "tools/call":
        return _handle_tools_call(id_value, params, has_params, context_provider)
    if method == "ping":
        return _handle_ping(id_value, params, has_params)
    return _error_response(id_value, METHOD_NOT_FOUND)
