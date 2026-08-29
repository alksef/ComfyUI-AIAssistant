"""Bounded in-memory page registry for WebSocket context sync.

Pure bookkeeping by design: this module imports only the standard library and
is fully testable without ComfyUI, aiohttp or any third-party package. It
tracks which browser tabs ("pages") are connected to the context-sync channel,
keeps one deep-copied snapshot per page, and never logs, reads state, or
touches the network; the enclosing WebSocket route decides how to frame the
result.
"""

from __future__ import annotations

import copy
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

PAGE_CAP = 8
_MAX_PAGE_ID_LENGTH = 128
_MAX_WORKFLOW_NAME_LENGTH = 128

_INVALID_PAGE_ID_ERROR = "invalid page id"
_UNKNOWN_PAGE_ERROR = "unknown page"
_DISCONNECTED_ERROR = "page is disconnected"
_INVALID_SNAPSHOT_ERROR = "snapshot must be a dict"

Clock = Callable[[], float]

__all__ = ["PageRegistry", "PAGE_CAP", "page_label"]


def page_label(page_id: str) -> str:
    """Human-readable badge label for a page id, ``AI-XXXX`` or the raw id."""
    if isinstance(page_id, str) and len(page_id) >= 4:
        return "AI-" + page_id[:4].upper()
    return page_id


def _is_valid_page_id(page_id: Any) -> bool:
    return isinstance(page_id, str) and 1 <= len(page_id) <= _MAX_PAGE_ID_LENGTH


def _workflow_name_of(snapshot: dict[str, Any]) -> str | None:
    workflow = snapshot.get("workflow")
    if not isinstance(workflow, dict):
        return None
    name = workflow.get("name")
    if not isinstance(name, str):
        name = workflow.get("title")
    if not isinstance(name, str):
        return None
    return name[:_MAX_WORKFLOW_NAME_LENGTH]


@dataclass
class _Page:
    connected: bool = False
    workflow_name: str | None = None
    snapshot: dict[str, Any] | None = None
    activated_at: float = 0.0
    activation_seq: int = 0


class PageRegistry:
    """Tracks connected pages and one deep-copied snapshot per page.

    ``now`` is an optional zero-argument callable returning a float, defaulting
    to ``time.time``. All methods return plain result dicts, never raise on
    invalid input, and never mutate their arguments.
    """

    def __init__(self, now: Clock | None = None) -> None:
        self._now = now if now is not None else time.time
        self._pages: dict[str, _Page] = {}
        self._seq = 0

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _evict_oldest(self) -> None:
        def key(item: tuple[str, _Page]) -> tuple[float, int, str]:
            page_id, page = item
            return (page.activated_at, page.activation_seq, page_id)

        disconnected = [(pid, p) for pid, p in self._pages.items() if not p.connected]
        pool = disconnected if disconnected else list(self._pages.items())
        victim = min(pool, key=key)
        del self._pages[victim[0]]

    def register(self, page_id: Any) -> dict[str, Any]:
        """Register or revive a page, marking it connected and activating it."""
        if not _is_valid_page_id(page_id):
            return {"ok": False, "error": _INVALID_PAGE_ID_ERROR}
        now = self._now()
        page = self._pages.get(page_id)
        if page is None:
            if len(self._pages) >= PAGE_CAP:
                self._evict_oldest()
            page = _Page()
            self._pages[page_id] = page
        page.connected = True
        page.activated_at = now
        page.activation_seq = self._next_seq()
        return {"ok": True}

    def record_snapshot(self, page_id: Any, snapshot: Any) -> dict[str, Any]:
        """Store a deep copy of ``snapshot`` for a known connected page."""
        if not _is_valid_page_id(page_id):
            return {"ok": False, "error": _INVALID_PAGE_ID_ERROR}
        page = self._pages.get(page_id)
        if page is None:
            return {"ok": False, "error": _UNKNOWN_PAGE_ERROR}
        if not page.connected:
            return {"ok": False, "error": _DISCONNECTED_ERROR}
        if not isinstance(snapshot, dict):
            return {"ok": False, "error": _INVALID_SNAPSHOT_ERROR}
        page.snapshot = copy.deepcopy(snapshot)
        page.workflow_name = _workflow_name_of(snapshot)
        return {"ok": True}

    def activate(self, page_id: Any) -> dict[str, Any]:
        """Refresh the activation time of a known connected page."""
        if not _is_valid_page_id(page_id):
            return {"ok": False, "error": _INVALID_PAGE_ID_ERROR}
        page = self._pages.get(page_id)
        if page is None:
            return {"ok": False, "error": _UNKNOWN_PAGE_ERROR}
        if not page.connected:
            return {"ok": False, "error": _DISCONNECTED_ERROR}
        page.activated_at = self._now()
        page.activation_seq = self._next_seq()
        return {"ok": True}

    def disconnect(self, page_id: Any) -> dict[str, Any]:
        """Mark a known page disconnected, keeping its snapshot and timestamps."""
        if not _is_valid_page_id(page_id):
            return {"ok": False, "error": _INVALID_PAGE_ID_ERROR}
        page = self._pages.get(page_id)
        if page is None:
            return {"ok": False, "error": _UNKNOWN_PAGE_ERROR}
        page.connected = False
        return {"ok": True}

    def active_page_id(self) -> str | None:
        """Page id of the most recently activated connected page, or ``None``."""
        best_id: str | None = None
        best_seq = -1
        for page_id, page in self._pages.items():
            if page.connected and page.activation_seq > best_seq:
                best_id = page_id
                best_seq = page.activation_seq
        return best_id

    def snapshot_for(self, page_id: Any) -> dict[str, Any] | None:
        """Deep copy of the stored snapshot for a known page, or ``None``."""
        if not isinstance(page_id, str):
            return None
        page = self._pages.get(page_id)
        if page is None or page.snapshot is None:
            return None
        return copy.deepcopy(page.snapshot)

    def summaries(self) -> list[dict[str, Any]]:
        """Deterministic summary of all pages, most recently activated first."""
        ordered = sorted(
            self._pages.items(),
            key=lambda item: (-item[1].activated_at, item[0]),
        )
        return [
            {
                "page_id": page_id,
                "page_label": page_label(page_id),
                "workflow_name": page.workflow_name,
                "connected": page.connected,
            }
            for page_id, page in ordered
        ]
