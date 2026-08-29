"""Contract tests for the bounded in-memory page registry.

The module under test imports only the standard library, so it is loaded
directly by file path under a unique module name and requires no ComfyUI, fake
``server`` module, or aiohttp. Importing the real top-level ``ai_assistant``
package is avoided because its ``__init__`` pulls in the ComfyUI backend.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MODULE_NAME = "_ai_assistant_pages_test"


def _load_module():
    path = _REPO_ROOT / "ai_assistant" / "pages.py"
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


PAGES = _load_module()

PageRegistry = PAGES.PageRegistry
PAGE_CAP = PAGES.PAGE_CAP
page_label = PAGES.page_label


class _RisingClock:
    """Zero-argument callable returning 1.0, 2.0, ... on successive calls."""

    def __init__(self) -> None:
        self._value = 0.0

    def __call__(self) -> float:
        self._value += 1.0
        return self._value


def _fixed_clock() -> float:
    return 10.0


def _snapshot(**overrides: Any) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "schema_version": "comfyui.ai-assistant.context/1",
        "workflow": {"name": "My Flow"},
        "selection": [{"id": 1, "title": "KSampler"}],
    }
    snapshot.update(overrides)
    return snapshot


class RegistrationTests(unittest.TestCase):
    def test_registers_valid_page_id(self):
        registry = PageRegistry()
        self.assertEqual(registry.register("tab-1"), {"ok": True})
        self.assertEqual(registry.active_page_id(), "tab-1")

    def test_register_implies_activation(self):
        registry = PageRegistry()
        registry.register("tab")
        self.assertEqual(registry.active_page_id(), "tab")

    def test_register_accepts_maximum_length_id(self):
        registry = PageRegistry()
        self.assertEqual(registry.register("x" * 128), {"ok": True})

    def test_register_rejects_invalid_ids(self):
        registry = PageRegistry()
        for page_id in ("", "x" * 129, 3, 3.5, None, True, ["a"], b"bytes"):
            with self.subTest(page_id=page_id):
                self.assertEqual(
                    registry.register(page_id),
                    {"ok": False, "error": "invalid page id"},
                )

    def test_exposes_page_cap_constant(self):
        self.assertEqual(PAGE_CAP, 8)


class SnapshotTests(unittest.TestCase):
    def test_record_snapshot_updates_workflow_name(self):
        registry = PageRegistry()
        registry.register("tab")
        registry.record_snapshot("tab", _snapshot())
        self.assertEqual(registry.summaries()[0]["workflow_name"], "My Flow")

    def test_record_snapshot_rejects_invalid_id(self):
        registry = PageRegistry()
        self.assertEqual(
            registry.record_snapshot("", _snapshot()),
            {"ok": False, "error": "invalid page id"},
        )

    def test_record_snapshot_unknown_page(self):
        registry = PageRegistry()
        self.assertEqual(
            registry.record_snapshot("ghost", _snapshot()),
            {"ok": False, "error": "unknown page"},
        )

    def test_record_snapshot_disconnected_page(self):
        registry = PageRegistry()
        registry.register("tab")
        registry.disconnect("tab")
        self.assertEqual(
            registry.record_snapshot("tab", _snapshot()),
            {"ok": False, "error": "page is disconnected"},
        )

    def test_record_snapshot_rejects_non_dict(self):
        registry = PageRegistry()
        registry.register("tab")
        for snapshot in ("x", [1], 3, None, True):
            with self.subTest(snapshot=snapshot):
                self.assertEqual(
                    registry.record_snapshot("tab", snapshot),
                    {"ok": False, "error": "snapshot must be a dict"},
                )

    def test_snapshot_for_unknown_page_is_none(self):
        registry = PageRegistry()
        self.assertIsNone(registry.snapshot_for("ghost"))

    def test_snapshot_for_before_record_is_none(self):
        registry = PageRegistry()
        registry.register("tab")
        self.assertIsNone(registry.snapshot_for("tab"))

    def test_snapshot_deep_copied_on_the_way_in(self):
        registry = PageRegistry()
        registry.register("tab")
        snapshot = _snapshot()
        registry.record_snapshot("tab", snapshot)
        snapshot["workflow"]["name"] = "Mutated"
        snapshot["selection"].append({"id": 2})
        stored = registry.snapshot_for("tab")
        self.assertEqual(stored["workflow"]["name"], "My Flow")
        self.assertEqual(stored["selection"], [{"id": 1, "title": "KSampler"}])

    def test_snapshot_deep_copied_on_the_way_out(self):
        registry = PageRegistry()
        registry.register("tab")
        registry.record_snapshot("tab", _snapshot())
        first = registry.snapshot_for("tab")
        first["workflow"]["name"] = "Mutated"
        first["selection"].clear()
        second = registry.snapshot_for("tab")
        self.assertEqual(second["workflow"]["name"], "My Flow")
        self.assertEqual(second["selection"], [{"id": 1, "title": "KSampler"}])


class WorkflowNameTests(unittest.TestCase):
    def _record(self, snapshot: dict[str, Any]) -> PageRegistry:
        registry = PageRegistry()
        registry.register("tab")
        registry.record_snapshot("tab", snapshot)
        return registry

    def test_workflow_name_truncated_to_128(self):
        registry = self._record(_snapshot(workflow={"name": "x" * 200}))
        self.assertEqual(registry.summaries()[0]["workflow_name"], "x" * 128)

    def test_missing_workflow_key_gives_none_name(self):
        registry = self._record({"selection": []})
        self.assertIsNone(registry.summaries()[0]["workflow_name"])

    def test_non_dict_workflow_gives_none_name(self):
        registry = self._record(_snapshot(workflow="not a dict"))
        self.assertIsNone(registry.summaries()[0]["workflow_name"])

    def test_non_string_workflow_name_gives_none(self):
        for name in (5, None, True, ["x"], {"n": "x"}):
            with self.subTest(name=name):
                registry = self._record(_snapshot(workflow={"name": name}))
                self.assertIsNone(registry.summaries()[0]["workflow_name"])

    def test_name_wins_over_title(self):
        registry = self._record(_snapshot(workflow={"name": "Name", "title": "Title"}))
        self.assertEqual(registry.summaries()[0]["workflow_name"], "Name")

    def test_title_used_when_name_absent(self):
        registry = self._record(_snapshot(workflow={"title": "Title"}))
        self.assertEqual(registry.summaries()[0]["workflow_name"], "Title")

    def test_title_used_when_name_non_string(self):
        registry = self._record(_snapshot(workflow={"name": 5, "title": "Title"}))
        self.assertEqual(registry.summaries()[0]["workflow_name"], "Title")

    def test_title_truncated_to_128(self):
        registry = self._record(_snapshot(workflow={"title": "x" * 200}))
        self.assertEqual(registry.summaries()[0]["workflow_name"], "x" * 128)

    def test_non_string_title_gives_none(self):
        for title in (5, None, True, ["x"], {"n": "x"}):
            with self.subTest(title=title):
                registry = self._record(_snapshot(workflow={"title": title}))
                self.assertIsNone(registry.summaries()[0]["workflow_name"])

    def test_both_name_and_title_absent_gives_none(self):
        registry = self._record(_snapshot(workflow={"extra": 1}))
        self.assertIsNone(registry.summaries()[0]["workflow_name"])


class ActivationTests(unittest.TestCase):
    def test_later_activate_wins_active_page(self):
        registry = PageRegistry(_RisingClock())
        registry.register("a")
        registry.register("b")
        self.assertEqual(registry.active_page_id(), "b")
        registry.activate("a")
        self.assertEqual(registry.active_page_id(), "a")

    def test_activate_rejects_invalid_id(self):
        registry = PageRegistry()
        self.assertEqual(
            registry.activate(""),
            {"ok": False, "error": "invalid page id"},
        )

    def test_activate_unknown_page(self):
        registry = PageRegistry()
        self.assertEqual(
            registry.activate("ghost"),
            {"ok": False, "error": "unknown page"},
        )

    def test_activate_disconnected_page(self):
        registry = PageRegistry()
        registry.register("tab")
        registry.disconnect("tab")
        self.assertEqual(
            registry.activate("tab"),
            {"ok": False, "error": "page is disconnected"},
        )


class DisconnectTests(unittest.TestCase):
    def test_disconnect_rejects_invalid_id(self):
        registry = PageRegistry()
        self.assertEqual(
            registry.disconnect(3),
            {"ok": False, "error": "invalid page id"},
        )

    def test_disconnect_unknown_page(self):
        registry = PageRegistry()
        self.assertEqual(
            registry.disconnect("ghost"),
            {"ok": False, "error": "unknown page"},
        )

    def test_disconnect_keeps_snapshot(self):
        registry = PageRegistry()
        registry.register("tab")
        registry.record_snapshot("tab", _snapshot())
        registry.disconnect("tab")
        self.assertEqual(registry.snapshot_for("tab"), _snapshot())

    def test_disconnect_of_active_page_falls_back(self):
        registry = PageRegistry(_RisingClock())
        registry.register("a")
        registry.register("b")
        self.assertEqual(registry.active_page_id(), "b")
        registry.disconnect("b")
        self.assertEqual(registry.active_page_id(), "a")

    def test_all_disconnected_active_is_none(self):
        registry = PageRegistry(_RisingClock())
        registry.register("a")
        registry.register("b")
        registry.disconnect("a")
        registry.disconnect("b")
        self.assertIsNone(registry.active_page_id())


class ReviveTests(unittest.TestCase):
    def test_revive_keeps_snapshot_and_reconnects(self):
        registry = PageRegistry()
        registry.register("tab")
        registry.record_snapshot("tab", _snapshot())
        registry.disconnect("tab")
        self.assertEqual(registry.register("tab"), {"ok": True})
        self.assertEqual(registry.active_page_id(), "tab")
        self.assertEqual(registry.snapshot_for("tab"), _snapshot())
        self.assertIs(registry.summaries()[0]["connected"], True)


class EvictionTests(unittest.TestCase):
    def test_ninth_register_evicts_oldest_activated(self):
        registry = PageRegistry(_RisingClock())
        for i in range(PAGE_CAP):
            registry.register(f"p{i}")
        self.assertEqual(registry.register("new"), {"ok": True})
        self.assertIsNone(registry.snapshot_for("p0"))
        self.assertEqual(registry.active_page_id(), "new")
        self.assertEqual(len(registry.summaries()), PAGE_CAP)

    def test_disconnected_page_is_evicted_first(self):
        registry = PageRegistry(_RisingClock())
        for i in range(PAGE_CAP):
            registry.register(f"p{i}")
        registry.disconnect("p3")
        self.assertEqual(registry.register("new"), {"ok": True})
        self.assertIsNone(registry.snapshot_for("p3"))
        ids = {summary["page_id"] for summary in registry.summaries()}
        self.assertIn("p0", ids)
        self.assertNotIn("p3", ids)
        self.assertEqual(len(ids), PAGE_CAP)


class SummaryTests(unittest.TestCase):
    def test_ordered_by_activation_descending(self):
        registry = PageRegistry(_RisingClock())
        registry.register("first")
        registry.register("second")
        registry.register("third")
        self.assertEqual(
            [summary["page_id"] for summary in registry.summaries()],
            ["third", "second", "first"],
        )

    def test_tie_breaks_by_page_id_ascending(self):
        registry = PageRegistry(_fixed_clock)
        registry.register("z")
        registry.register("a")
        self.assertEqual(
            [summary["page_id"] for summary in registry.summaries()],
            ["a", "z"],
        )

    def test_exposes_only_public_fields(self):
        registry = PageRegistry()
        registry.register("tab")
        registry.record_snapshot("tab", _snapshot())
        summary = registry.summaries()[0]
        self.assertEqual(
            set(summary.keys()),
            {"page_id", "page_label", "workflow_name", "connected"},
        )
        self.assertEqual(summary["page_id"], "tab")
        self.assertEqual(summary["page_label"], "tab")
        self.assertEqual(summary["workflow_name"], "My Flow")
        self.assertIs(summary["connected"], True)

    def test_empty_registry_has_no_summaries(self):
        registry = PageRegistry()
        self.assertEqual(registry.summaries(), [])


class PageLabelTests(unittest.TestCase):
    def test_label_uppercases_first_four_chars(self):
        self.assertEqual(page_label("a1b2-c3d4"), "AI-A1B2")

    def test_label_for_uuid_like_id(self):
        self.assertEqual(page_label("f47ac10b-58cc"), "AI-F47A")

    def test_short_id_returns_raw_id(self):
        for page_id in ("", "a", "ab", "abc"):
            with self.subTest(page_id=page_id):
                self.assertEqual(page_label(page_id), page_id)

    def test_non_string_returns_raw_value(self):
        for value in (3, 3.5, None, True, ["a"], b"bytes"):
            with self.subTest(value=value):
                self.assertEqual(page_label(value), value)

    def test_label_never_raises(self):
        for value in (3, 3.5, None, True, ["a"], b"bytes", ""):
            with self.subTest(value=value):
                page_label(value)

    def test_summary_label_for_uuid_like_id(self):
        registry = PageRegistry()
        registry.register("f47ac10b-58cc")
        self.assertEqual(registry.summaries()[0]["page_label"], "AI-F47A")

    def test_summary_label_for_short_id(self):
        registry = PageRegistry()
        registry.register("abc")
        self.assertEqual(registry.summaries()[0]["page_label"], "abc")


if __name__ == "__main__":
    unittest.main()
