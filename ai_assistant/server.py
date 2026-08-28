"""Volatile in-process mailbox and versioned context routes.

All snapshot state lives only in process memory. The package adds no
executable workflow nodes and never logs, persists, or echoes payloads.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any

from aiohttp import web
from server import PromptServer

from .mcp_protocol import JSONRPC_VERSION, PARSE_ERROR, dispatch

SCHEMA_VERSION = "comfyui.ai-assistant.context/1"
CONTEXT_PATH = "/ai-assistant/context"
MCP_PATH = "/mcp"
MAX_BODY_BYTES = 128 * 1024
MAX_MCP_BODY_BYTES = 64 * 1024
_CHUNK_SIZE = 8192


class BodyTooLarge(Exception):
    """Raised when a request body exceeds the configured byte limit."""


class ContextMailbox:
    """Stores at most one normalized snapshot in process memory."""

    def __init__(self) -> None:
        self._snapshot: dict[str, Any] | None = None
        self._received_at: str | None = None

    @property
    def available(self) -> bool:
        return self._snapshot is not None

    @property
    def received_at(self) -> str | None:
        return self._received_at

    def replace(self, snapshot: dict[str, Any]) -> None:
        self._snapshot = copy.deepcopy(snapshot)
        self._received_at = datetime.now(timezone.utc).isoformat()

    def snapshot_copy(self) -> dict[str, Any] | None:
        if self._snapshot is None:
            return None
        return copy.deepcopy(self._snapshot)


_mailbox = ContextMailbox()


def _normalize(payload: Any) -> dict[str, Any]:
    """Validate a raw JSON value and narrow it to the accepted snapshot shape."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")

    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported schema version")

    captured_at = payload.get("captured_at")
    if not isinstance(captured_at, str) or not captured_at:
        raise ValueError("invalid capture timestamp")

    revision = payload.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("invalid revision")

    workflow = payload.get("workflow")
    if workflow is not None and not isinstance(workflow, dict):
        raise ValueError("invalid workflow")

    selection = payload.get("selection")
    if not isinstance(selection, list):
        raise ValueError("invalid selection")

    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at": captured_at,
        "revision": revision,
        "workflow": copy.deepcopy(workflow),
        "selection": copy.deepcopy(selection),
    }


def _json(payload: dict[str, Any], status: int = 200) -> web.Response:
    response = web.json_response(payload, status=status)
    response.headers["Cache-Control"] = "no-store"
    return response


def _unavailable_envelope() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "available": False,
        "received_at": None,
        "snapshot": None,
    }


def _context_envelope() -> dict[str, Any]:
    if not _mailbox.available:
        return _unavailable_envelope()
    return {
        "schema_version": SCHEMA_VERSION,
        "available": True,
        "received_at": _mailbox.received_at,
        "snapshot": _mailbox.snapshot_copy(),
    }


async def handle_get(request: web.Request) -> web.Response:
    return _json(_context_envelope())


async def _read_bounded_body(request: web.Request, limit: int = MAX_BODY_BYTES) -> bytes:
    declared = request.content_length
    if declared is not None and declared > limit:
        raise BodyTooLarge

    chunks: list[bytes] = []
    size = 0
    async for chunk in request.content.iter_chunked(_CHUNK_SIZE):
        size += len(chunk)
        if size > limit:
            raise BodyTooLarge
        chunks.append(chunk)
    return b"".join(chunks)


async def handle_post(request: web.Request) -> web.Response:
    try:
        body = await _read_bounded_body(request)
    except BodyTooLarge:
        return _json({"error": "request body too large"}, status=413)

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _json({"error": "request body must be valid JSON"}, status=400)

    try:
        snapshot = _normalize(payload)
    except ValueError:
        return _json({"error": "invalid context snapshot"}, status=400)

    _mailbox.replace(snapshot)
    return _json({"accepted": True, "revision": snapshot["revision"]})


def _mcp_parse_error() -> web.Response:
    return _json(
        {
            "jsonrpc": JSONRPC_VERSION,
            "id": None,
            "error": {"code": PARSE_ERROR, "message": "Parse error"},
        }
    )


def _mcp_no_content() -> web.Response:
    response = web.Response(status=202)
    response.headers["Cache-Control"] = "no-store"
    return response


def _mcp_method_not_allowed() -> web.Response:
    return web.Response(
        status=405,
        text="method not allowed",
        headers={"Allow": "POST", "Cache-Control": "no-store"},
    )


def _mcp_unsupported_media_type() -> web.Response:
    return web.Response(
        status=415,
        text="unsupported media type",
        headers={"Cache-Control": "no-store"},
    )


def _mcp_body_too_large() -> web.Response:
    return web.Response(
        status=413,
        text="request body too large",
        headers={"Cache-Control": "no-store"},
    )


async def handle_mcp(request: web.Request) -> web.Response:
    if request.method != "POST":
        return _mcp_method_not_allowed()

    content_type = request.headers.get("Content-Type", "")
    if content_type.split(";", 1)[0].strip().lower() != "application/json":
        return _mcp_unsupported_media_type()

    try:
        body = await _read_bounded_body(request, MAX_MCP_BODY_BYTES)
    except BodyTooLarge:
        return _mcp_body_too_large()

    try:
        message = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _mcp_parse_error()

    response = dispatch(message, _context_envelope)
    if response is None:
        return _mcp_no_content()
    return _json(response)


def register_routes() -> None:
    routes = PromptServer.instance.routes
    routes.get(CONTEXT_PATH)(handle_get)
    routes.post(CONTEXT_PATH)(handle_post)
    routes.route("*", MCP_PATH)(handle_mcp)
