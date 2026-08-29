"""Pure command validation and result shaping for the write tool.

Stdlib only by design: this module imports only the standard library, performs
no I/O, never raises on bad input, and returns plain dicts. It validates the
``set_widget_text`` tool's params against its contract, resolves the selection
state from a context envelope, checks the revision CAS, shapes MCP tool
results, and builds the downstream command frame. The enclosing server decides
how to execute the command.
"""

from __future__ import annotations

import json
from typing import Any

MAX_TEXT_LENGTH = 8192
MAX_WIDGET_NAME_LENGTH = 128
TEXT_WIDGET_TYPES = ("text", "customtext", "string")

_INVALID_PARAMS_SHAPE_ERROR = "invalid params shape"
_INVALID_PARAMS_KEYS_ERROR = "invalid params keys"
_INVALID_WIDGET_NAME_ERROR = "invalid widget name"
_INVALID_TEXT_ERROR = "invalid text"
_INVALID_REVISION_ERROR = "invalid expected revision"
_NO_SELECTION_ERROR = "no selection available"
_NO_NODE_SELECTED_ERROR = "no node selected"
_MULTIPLE_NODES_ERROR = "multiple nodes selected"
_UNKNOWN_WIDGET_ERROR = "unknown widget"
_NOT_TEXT_LIKE_ERROR = "widget is not text-like"
_REVISION_MISMATCH_ERROR = "revision mismatch"

__all__ = [
    "MAX_TEXT_LENGTH",
    "MAX_WIDGET_NAME_LENGTH",
    "TEXT_WIDGET_TYPES",
    "validate_params",
    "resolve_selection",
    "check_revision",
    "success_result",
    "failure_result",
    "build_command",
]


def validate_params(params: Any) -> dict[str, Any]:
    """Validate the ``set_widget_text`` tool arguments."""
    if not isinstance(params, dict):
        return {"ok": False, "error": _INVALID_PARAMS_SHAPE_ERROR}
    if set(params) != {"widget", "text", "expected_revision"}:
        return {"ok": False, "error": _INVALID_PARAMS_KEYS_ERROR}
    widget = params["widget"]
    if not isinstance(widget, str) or not 1 <= len(widget) <= MAX_WIDGET_NAME_LENGTH:
        return {"ok": False, "error": _INVALID_WIDGET_NAME_ERROR}
    text = params["text"]
    if not isinstance(text, str) or len(text) > MAX_TEXT_LENGTH:
        return {"ok": False, "error": _INVALID_TEXT_ERROR}
    expected_revision = params["expected_revision"]
    if (
        isinstance(expected_revision, bool)
        or not isinstance(expected_revision, int)
        or expected_revision < 0
    ):
        return {"ok": False, "error": _INVALID_REVISION_ERROR}
    return {
        "ok": True,
        "widget": widget,
        "text": text,
        "expected_revision": expected_revision,
    }


def resolve_selection(envelope: Any, widget: Any) -> dict[str, Any]:
    """Decide whether the envelope allows a write to ``widget``."""
    if not isinstance(envelope, dict):
        return {"ok": False, "error": _NO_SELECTION_ERROR}
    snapshot = envelope.get("snapshot")
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
    widgets = selection[0].get("widgets")
    if not isinstance(widgets, list):
        return {"ok": False, "error": _UNKNOWN_WIDGET_ERROR}
    for row in widgets:
        if not isinstance(row, dict) or row.get("name") != widget:
            continue
        if row.get("type") not in TEXT_WIDGET_TYPES:
            return {"ok": False, "error": _NOT_TEXT_LIKE_ERROR}
        return {"ok": True}
    return {"ok": False, "error": _UNKNOWN_WIDGET_ERROR}


def check_revision(envelope: Any, expected_revision: int) -> dict[str, Any]:
    """Compare the envelope's snapshot revision against ``expected_revision``."""
    if not isinstance(envelope, dict):
        return {
            "ok": False,
            "error": _REVISION_MISMATCH_ERROR,
            "current_revision": None,
        }
    snapshot = envelope.get("snapshot")
    if not isinstance(snapshot, dict):
        return {
            "ok": False,
            "error": _REVISION_MISMATCH_ERROR,
            "current_revision": None,
        }
    current_revision = snapshot.get("revision")
    if current_revision != expected_revision:
        return {
            "ok": False,
            "error": _REVISION_MISMATCH_ERROR,
            "current_revision": current_revision,
        }
    return {"ok": True}


def success_result(status: str, revision: Any, widget: str) -> dict[str, Any]:
    """MCP tool result for an applied (or queued) write."""
    text = json.dumps(
        {"status": status, "revision": revision, "widget": widget},
        separators=(",", ":"),
    )
    return {"content": [{"type": "text", "text": text}], "isError": False}


def failure_result(message: str, current_revision: Any = None) -> dict[str, Any]:
    """MCP tool result for a refused write."""
    payload: dict[str, Any] = {"error": message}
    if current_revision is not None:
        payload["current_revision"] = current_revision
    text = json.dumps(payload, separators=(",", ":"))
    return {"content": [{"type": "text", "text": text}], "isError": True}


def build_command(command_id: str, widget: str, text: str) -> dict[str, Any]:
    """Downstream command frame pushed to the page socket."""
    return {
        "type": "command",
        "command_id": command_id,
        "op": "set_widget_text",
        "widget": widget,
        "text": text,
    }
