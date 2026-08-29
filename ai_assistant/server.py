"""Volatile in-process mailbox and versioned context routes.

All snapshot state lives only in process memory. The package adds no
executable workflow nodes and never logs, persists, or echoes payloads.
"""

from __future__ import annotations

import asyncio
import copy
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from aiohttp import WSMsgType, web
from server import PromptServer

from . import commands
from .mcp_protocol import JSONRPC_VERSION, PARSE_ERROR, dispatch
from .pages import PageRegistry, page_label

SCHEMA_VERSION = "comfyui.ai-assistant.context/1"
CONTEXT_PATH = "/ai-assistant/context"
MCP_PATH = "/mcp"
WS_PATH = "/ai-assistant/ws"
MAX_BODY_BYTES = 128 * 1024
MAX_MCP_BODY_BYTES = 64 * 1024
_CHUNK_SIZE = 8192

WRITE_CONFIRM_TIMEOUT = 3.0
_POLL_INTERVAL = 0.15

_WS_HEARTBEAT = 20.0
_WS_ERROR_INVALID_JSON = "invalid json"
_WS_ERROR_NOT_OBJECT = "message must be a JSON object"
_WS_ERROR_UNKNOWN_TYPE = "unknown message type"
_WS_ERROR_BINARY = "binary frames are not supported"
_WS_ERROR_REGISTER = "register failed"
_WS_ERROR_SNAPSHOT = "snapshot rejected"
_WS_ERROR_ACTIVATE = "activate failed"


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
_registry = PageRegistry()
_mailbox_mirrored_page: str | None = None
_page_sockets: dict[str, web.WebSocketResponse] = {}
_pending_write: dict[str, Any] | None = None


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
        envelope = _unavailable_envelope()
    else:
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "available": True,
            "received_at": _mailbox.received_at,
            "snapshot": _mailbox.snapshot_copy(),
        }
    envelope["pages"] = _registry.summaries()
    active = _registry.active_page_id()
    envelope["active_page"] = (
        None
        if active is None
        else {"page_id": active, "page_label": page_label(active), "connected": True}
    )
    return envelope


def _mirror_mailbox() -> None:
    """Copy the active page's stored snapshot into the mailbox when it changed."""
    global _mailbox_mirrored_page
    active = _registry.active_page_id()
    if active is None or active == _mailbox_mirrored_page:
        return
    snapshot = _registry.snapshot_for(active)
    if snapshot is None:
        return
    _mailbox.replace(snapshot)
    _mailbox_mirrored_page = active


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
    global _mailbox_mirrored_page
    _mailbox_mirrored_page = None
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


def _prune_page_sockets() -> None:
    """Drop socket-map entries for pages the registry no longer tracks."""
    connected = {page["page_id"] for page in _registry.summaries() if page["connected"]}
    for page_id in [pid for pid in _page_sockets if pid not in connected]:
        _page_sockets.pop(page_id, None)


async def _send_command(ws: web.WebSocketResponse, frame: dict[str, Any]) -> None:
    try:
        await ws.send_json(frame)
    except Exception:
        pass


def _handle_set_widget_text(params: dict[str, Any]) -> dict[str, Any]:
    arguments = params.get("arguments") if isinstance(params, dict) else None
    validated = commands.validate_params(arguments)
    if not validated.get("ok"):
        return commands.failure_result(validated["error"])
    widget = validated["widget"]
    text = validated["text"]
    expected_revision = validated["expected_revision"]
    expected_page = validated["expected_page"]

    envelope = _context_envelope()
    selection = commands.resolve_selection(envelope, widget)
    if not selection.get("ok"):
        return commands.failure_result(selection["error"])

    active = _registry.active_page_id()
    ws = None if active is None else _page_sockets.get(active)
    if ws is None:
        return commands.failure_result("no active page")

    if expected_page != active:
        snapshot = envelope.get("snapshot")
        current_revision = snapshot.get("revision") if isinstance(snapshot, dict) else None
        return commands.failure_result("active page changed", current_revision)

    revision = commands.check_revision(envelope, expected_revision)
    if not revision.get("ok"):
        return commands.failure_result("revision mismatch", revision.get("current_revision"))

    command_id = uuid.uuid4().hex
    frame = commands.build_command(command_id, widget, text)
    asyncio.create_task(_send_command(ws, frame))

    global _pending_write
    if _pending_write is None:
        _pending_write = {
            "command_id": command_id,
            "widget": widget,
            "expected_revision": expected_revision,
            "deadline": asyncio.get_running_loop().time() + WRITE_CONFIRM_TIMEOUT,
        }
    return commands.success_result("queued", expected_revision, widget)


async def _confirm_write(response: dict[str, Any]) -> dict[str, Any]:
    """Poll for a revision advance within the bounded wait, then reply."""
    global _pending_write
    pending = _pending_write
    expected_revision = pending["expected_revision"]
    widget = pending["widget"]
    deadline = pending["deadline"]
    loop = asyncio.get_running_loop()
    try:
        while loop.time() < deadline:
            await asyncio.sleep(_POLL_INTERVAL)
            envelope = _context_envelope()
            snapshot = envelope.get("snapshot")
            revision = snapshot.get("revision") if isinstance(snapshot, dict) else None
            if isinstance(revision, int) and revision > expected_revision:
                response["result"] = commands.success_result("applied", revision, widget)
                return response
    finally:
        _pending_write = None
    return response


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

    pending_before = _pending_write is not None
    response = dispatch(message, _context_envelope, command_handler=_handle_set_widget_text)
    if response is None:
        return _mcp_no_content()
    if _pending_write is not None and not pending_before:
        response = await _confirm_write(response)
    return _json(response)


async def _ws_send_error(ws: web.WebSocketResponse, error: str) -> None:
    await ws.send_json({"type": "error", "ok": False, "error": error})


async def _ws_handle_register(
    ws: web.WebSocketResponse,
    message: dict[str, Any],
    page_id: str | None,
) -> str | None:
    new_page_id = message.get("page_id")
    if page_id is not None and new_page_id != page_id:
        _registry.disconnect(page_id)
        _page_sockets.pop(page_id, None)
    if not _registry.register(new_page_id).get("ok"):
        await _ws_send_error(ws, _WS_ERROR_REGISTER)
        return None
    _page_sockets[new_page_id] = ws
    _prune_page_sockets()
    _mirror_mailbox()
    await ws.send_json({"type": "registered", "ok": True})
    return new_page_id


async def _ws_handle_snapshot(
    ws: web.WebSocketResponse,
    message: dict[str, Any],
) -> None:
    page_id = message.get("page_id")
    try:
        snapshot = _normalize(message.get("snapshot"))
    except ValueError:
        await _ws_send_error(ws, _WS_ERROR_SNAPSHOT)
        return
    if not _registry.record_snapshot(page_id, snapshot).get("ok"):
        await _ws_send_error(ws, _WS_ERROR_SNAPSHOT)
        return
    global _mailbox_mirrored_page
    if _registry.active_page_id() == page_id:
        _mailbox.replace(snapshot)
        _mailbox_mirrored_page = page_id
    await ws.send_json({"type": "accepted", "ok": True, "revision": snapshot["revision"]})


async def _ws_handle_activate(
    ws: web.WebSocketResponse,
    message: dict[str, Any],
) -> None:
    page_id = message.get("page_id")
    if not _registry.activate(page_id).get("ok"):
        await _ws_send_error(ws, _WS_ERROR_ACTIVATE)
        return
    _mirror_mailbox()
    await ws.send_json({"type": "activated", "ok": True})


async def _ws_handle_message(
    ws: web.WebSocketResponse,
    data: str,
    page_id: str | None,
) -> str | None:
    try:
        message = json.loads(data)
    except (UnicodeDecodeError, ValueError):
        await _ws_send_error(ws, _WS_ERROR_INVALID_JSON)
        return page_id
    if not isinstance(message, dict):
        await _ws_send_error(ws, _WS_ERROR_NOT_OBJECT)
        return page_id
    message_type = message.get("type")
    if message_type == "register":
        return await _ws_handle_register(ws, message, page_id)
    if message_type == "snapshot":
        await _ws_handle_snapshot(ws, message)
        return page_id
    if message_type == "activate":
        await _ws_handle_activate(ws, message)
        return page_id
    await _ws_send_error(ws, _WS_ERROR_UNKNOWN_TYPE)
    return page_id


async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=_WS_HEARTBEAT, max_msg_size=MAX_BODY_BYTES)
    await ws.prepare(request)
    page_id: str | None = None
    try:
        async for message in ws:
            if message.type == WSMsgType.TEXT:
                page_id = await _ws_handle_message(ws, message.data, page_id)
            elif message.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                break
            else:
                await _ws_send_error(ws, _WS_ERROR_BINARY)
    finally:
        if page_id is not None:
            _registry.disconnect(page_id)
            _page_sockets.pop(page_id, None)
        _mirror_mailbox()
    return ws


def register_routes() -> None:
    routes = PromptServer.instance.routes
    routes.get(CONTEXT_PATH)(handle_get)
    routes.post(CONTEXT_PATH)(handle_post)
    routes.route("*", MCP_PATH)(handle_mcp)
    routes.get(WS_PATH)(handle_ws)
