"""Pure param validation, preview policy and result shaping for widget reads.

Stdlib only by design: this module imports only the standard library,
performs no I/O, never raises on bad input, and returns plain dicts. It
validates the ``get_widget_text`` tool's params against its contract,
resolves the widget row from a stored snapshot (full values, not the
previewed envelope), pages the text, and shapes MCP tool results. The
enclosing server decides how to transport the answer. Error literals
mirror ``commands.py`` so consumers see one vocabulary.
"""

from __future__ import annotations

import json
from typing import Any

from .commands import MAX_WIDGET_NAME_LENGTH, TEXT_WIDGET_TYPES

DEFAULT_LIMIT = 32768
MAX_LIMIT = 32768
PREVIEW_CHARS = 512

_INVALID_PARAMS_SHAPE_ERROR = "invalid params shape"
_INVALID_PARAMS_KEYS_ERROR = "invalid params keys"
_INVALID_WIDGET_NAME_ERROR = "invalid widget name"
_INVALID_OFFSET_ERROR = "invalid offset"
_INVALID_LIMIT_ERROR = "invalid limit"
_NO_SELECTION_ERROR = "no selection available"
_NO_NODE_SELECTED_ERROR = "no node selected"
_MULTIPLE_NODES_ERROR = "multiple nodes selected"
_UNKNOWN_WIDGET_ERROR = "unknown widget"
_NOT_TEXT_LIKE_ERROR = "widget is not text-like"

__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "PREVIEW_CHARS",
    "validate_params",
    "read_text",
    "preview_snapshot",
    "page",
    "success_result",
    "failure_result",
]


def validate_params(params: Any) -> dict[str, Any]:
    """Validate the ``get_widget_text`` tool arguments."""
    if not isinstance(params, dict):
        return {"ok": False, "error": _INVALID_PARAMS_SHAPE_ERROR}
    if set(params) - {"widget", "offset", "limit"}:
        return {"ok": False, "error": _INVALID_PARAMS_KEYS_ERROR}
    widget = params.get("widget")
    if not isinstance(widget, str) or not 1 <= len(widget) <= MAX_WIDGET_NAME_LENGTH:
        return {"ok": False, "error": _INVALID_WIDGET_NAME_ERROR}
    offset = params.get("offset", 0)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        return {"ok": False, "error": _INVALID_OFFSET_ERROR}
    limit = params.get("limit", DEFAULT_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        return {"ok": False, "error": _INVALID_LIMIT_ERROR}
    return {"ok": True, "widget": widget, "offset": offset, "limit": limit}


def read_text(snapshot: Any, widget: str) -> dict[str, Any]:
    """Resolve ``widget`` against a stored snapshot and return its full value.

    ``snapshot`` is the mailbox's stored snapshot with full values, not the
    previewed envelope the read routes serve.
    """
    if not isinstance(snapshot, dict):
        return {"ok": False, "error": _NO_SELECTION_ERROR}
    workflow = snapshot.get("workflow")
    if not isinstance(workflow, dict):
        return {"ok": False, "error": _MULTIPLE_NODES_ERROR}
    if workflow.get("selected_count") == 0 or workflow.get("selection_detail") == "none":
        return {"ok": False, "error": _NO_NODE_SELECTED_ERROR}
    if workflow.get("selection_detail") != "full":
        return {"ok": False, "error": _MULTIPLE_NODES_ERROR}
    selection = snapshot.get("selection")
    if not isinstance(selection, list) or not selection:
        return {"ok": False, "error": _NO_NODE_SELECTED_ERROR}
    widgets = selection[0].get("widgets") if isinstance(selection[0], dict) else None
    if not isinstance(widgets, list):
        return {"ok": False, "error": _UNKNOWN_WIDGET_ERROR}
    for row in widgets:
        if not isinstance(row, dict) or row.get("name") != widget:
            continue
        if row.get("type") not in TEXT_WIDGET_TYPES:
            return {"ok": False, "error": _NOT_TEXT_LIKE_ERROR}
        value = row.get("value")
        if not isinstance(value, str):
            return {"ok": False, "error": _NOT_TEXT_LIKE_ERROR}
        return {"ok": True, "value": value, "revision": snapshot.get("revision")}
    return {"ok": False, "error": _UNKNOWN_WIDGET_ERROR}


def preview_snapshot(snapshot: dict[str, Any]) -> None:
    """Shrink long string values in a snapshot copy to a preview, in place.

    Values up to ``PREVIEW_CHARS`` travel whole (exactly what older versions
    already delivered); longer ones become a prefix plus an ellipsis with the
    total character count in the additive ``length`` field, replacing the old
    ``<truncated>`` dead end. A ``length`` set by the page (transport clip)
    always wins so the count stays truthful beyond the clip.
    """
    selection = snapshot.get("selection")
    if not isinstance(selection, list):
        return
    for node in selection:
        if not isinstance(node, dict):
            continue
        widgets = node.get("widgets")
        if not isinstance(widgets, list):
            continue
        for row in widgets:
            if not isinstance(row, dict):
                continue
            value = row.get("value")
            if not isinstance(value, str) or len(value) <= PREVIEW_CHARS:
                continue
            reported = row.get("length")
            if isinstance(reported, int) and not isinstance(reported, bool):
                total = reported
            else:
                total = len(value)
            row["value"] = value[: PREVIEW_CHARS - 1] + "…"
            row["length"] = total


def page(revision: Any, widget: str, offset: int, limit: int, text: str) -> dict[str, Any]:
    """One page of the widget's full text as a plain payload dict."""
    return {
        "revision": revision,
        "widget": widget,
        "offset": offset,
        "limit": limit,
        "length": len(text),
        "text": text[offset : offset + limit],
        "truncated": offset + limit < len(text),
    }


def success_result(
    revision: Any, widget: str, offset: int, limit: int, text: str
) -> dict[str, Any]:
    """MCP tool result carrying one page of the widget's full text."""
    payload = json.dumps(page(revision, widget, offset, limit, text), separators=(",", ":"))
    return {"content": [{"type": "text", "text": payload}], "isError": False}


def failure_result(message: str) -> dict[str, Any]:
    """MCP tool result for a refused read."""
    payload = json.dumps({"error": message}, separators=(",", ":"))
    return {"content": [{"type": "text", "text": payload}], "isError": True}
