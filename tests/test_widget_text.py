"""Pure contract tests for the widget-text read module.

The module under test is loaded through the package init (it imports
``.commands``), so a minimal fake ``server`` module stands in for ComfyUI's
the same way ``test_server.py`` does — no running ComfyUI required.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PKG_NAME = "_ai_assistant_widget_text_test_pkg"


def _load_widget_text():
    fake_server = types.ModuleType("server")
    fake_server.PromptServer = type("PromptServer", (), {"instance": None})
    sys.modules["server"] = fake_server
    pkg_spec = importlib.util.spec_from_file_location(
        _PKG_NAME,
        _REPO_ROOT / "ai_assistant" / "__init__.py",
        submodule_search_locations=[str(_REPO_ROOT / "ai_assistant")],
    )
    package = importlib.util.module_from_spec(pkg_spec)
    sys.modules[_PKG_NAME] = package
    pkg_spec.loader.exec_module(package)
    spec = importlib.util.spec_from_file_location(
        f"{_PKG_NAME}.widget_text", _REPO_ROOT / "ai_assistant" / "widget_text.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{_PKG_NAME}.widget_text"] = module
    spec.loader.exec_module(module)
    return module


widget_text = _load_widget_text()


def _snapshot(value: object, *, widget_type: str = "text", detail: str = "full") -> dict:
    return {
        "schema_version": "comfyui.ai-assistant.context/1",
        "captured_at": "2026-09-04T10:00:00+00:00",
        "revision": 9,
        "workflow": {"selection_detail": detail, "selected_count": 1},
        "selection": [
            {
                "id": 3,
                "type": "CLIPTextEncode",
                "widgets": [
                    {"name": "text", "type": widget_type, "value": value},
                ],
            }
        ],
    }


class ValidateParamsTests(unittest.TestCase):
    def test_non_dict_arguments_are_shape_errors(self):
        for params in (None, "text", 7, []):
            with self.subTest(params=params):
                self.assertEqual(
                    widget_text.validate_params(params),
                    {"ok": False, "error": "invalid params shape"},
                )

    def test_unknown_keys_are_rejected(self):
        self.assertEqual(
            widget_text.validate_params({"widget": "text", "extra": 1}),
            {"ok": False, "error": "invalid params keys"},
        )

    def test_widget_name_bounds(self):
        for bad in ("", None, 5, "w" * 129):
            with self.subTest(bad=bad):
                self.assertEqual(
                    widget_text.validate_params({"widget": bad}),
                    {"ok": False, "error": "invalid widget name"},
                )

    def test_offset_and_limit_bounds(self):
        for params, error in (
            ({"widget": "t", "offset": -1}, "invalid offset"),
            ({"widget": "t", "offset": True}, "invalid offset"),
            ({"widget": "t", "offset": "0"}, "invalid offset"),
            ({"widget": "t", "limit": 0}, "invalid limit"),
            ({"widget": "t", "limit": widget_text.MAX_LIMIT + 1}, "invalid limit"),
            ({"widget": "t", "limit": False}, "invalid limit"),
        ):
            with self.subTest(params=params):
                self.assertEqual(
                    widget_text.validate_params(params),
                    {"ok": False, "error": error},
                )

    def test_defaults_and_valid_values(self):
        self.assertEqual(
            widget_text.validate_params({"widget": "text"}),
            {"ok": True, "widget": "text", "offset": 0, "limit": widget_text.DEFAULT_LIMIT},
        )
        self.assertEqual(
            widget_text.validate_params({"widget": "text", "offset": 5, "limit": 10}),
            {"ok": True, "widget": "text", "offset": 5, "limit": 10},
        )


class ReadTextTests(unittest.TestCase):
    def test_unusable_snapshots_map_to_static_errors(self):
        cases = [
            (None, "no selection available"),
            ("x", "no selection available"),
            (_snapshot("v", detail="multiple"), "multiple nodes selected"),
            (_snapshot("v", detail="none"), "no node selected"),
            ({"workflow": {"selection_detail": "full"}, "selection": []}, "no node selected"),
        ]
        for snapshot, error in cases:
            with self.subTest(snapshot=snapshot):
                self.assertEqual(
                    widget_text.read_text(snapshot, "text"),
                    {"ok": False, "error": error},
                )

    def test_unknown_and_non_text_widgets(self):
        snapshot = {
            "workflow": {"selection_detail": "full"},
            "selection": [{"widgets": [{"name": "seed", "type": "INT", "value": 1}]}],
        }
        self.assertEqual(
            widget_text.read_text(snapshot, "nope"),
            {"ok": False, "error": "unknown widget"},
        )
        self.assertEqual(
            widget_text.read_text(snapshot, "seed"),
            {"ok": False, "error": "widget is not text-like"},
        )

    def test_non_string_text_value_is_not_text_like(self):
        snapshot = _snapshot(42)
        self.assertEqual(
            widget_text.read_text(snapshot, "text"),
            {"ok": False, "error": "widget is not text-like"},
        )

    def test_happy_path_returns_value_and_revision(self):
        snapshot = _snapshot("привет")
        self.assertEqual(
            widget_text.read_text(snapshot, "text"),
            {"ok": True, "value": "привет", "revision": 9},
        )


class PreviewSnapshotTests(unittest.TestCase):
    def test_short_values_are_untouched(self):
        snapshot = _snapshot("x" * 512)
        before = json.dumps(snapshot, sort_keys=True)
        widget_text.preview_snapshot(snapshot)
        self.assertEqual(json.dumps(snapshot, sort_keys=True), before)

    def test_long_values_become_preview_with_total_length(self):
        snapshot = _snapshot("y" * 600)
        widget_text.preview_snapshot(snapshot)
        row = snapshot["selection"][0]["widgets"][0]
        self.assertEqual(len(row["value"]), widget_text.PREVIEW_CHARS)
        self.assertTrue(row["value"].endswith("…"))
        self.assertTrue(row["value"].startswith("y" * 100))
        self.assertEqual(row["length"], 600)

    def test_page_reported_length_wins_over_the_clipped_value(self):
        snapshot = _snapshot("z" * 32769)
        snapshot["selection"][0]["widgets"][0]["length"] = 40000
        widget_text.preview_snapshot(snapshot)
        row = snapshot["selection"][0]["widgets"][0]
        self.assertEqual(row["length"], 40000)

    def test_non_string_values_and_odd_shapes_are_ignored(self):
        snapshot = _snapshot(42)
        snapshot["selection"].append("just-a-name")
        snapshot["selection"].append({"widgets": "not-a-list"})
        before = json.dumps(snapshot, sort_keys=True)
        widget_text.preview_snapshot(snapshot)
        self.assertEqual(json.dumps(snapshot, sort_keys=True), before)


class ResultShapingTests(unittest.TestCase):
    def test_page_slices_and_flags_truncation(self):
        paged = widget_text.page(7, "text", 10, 5, "abcdefghij")
        self.assertEqual(
            paged,
            {
                "revision": 7,
                "widget": "text",
                "offset": 10,
                "limit": 5,
                "length": 10,
                "text": "",
                "truncated": False,
            },
        )
        paged = widget_text.page(7, "text", 0, 5, "abcdefghij")
        self.assertEqual(paged["text"], "abcde")
        self.assertIs(paged["truncated"], True)

    def test_success_and_failure_results(self):
        result = widget_text.success_result(7, "text", 0, 5, "abcdefghij")
        self.assertIs(result["isError"], False)
        self.assertEqual(json.loads(result["content"][0]["text"])["text"], "abcde")
        failure = widget_text.failure_result("unknown widget")
        self.assertIs(failure["isError"], True)
        self.assertEqual(json.loads(failure["content"][0]["text"]), {"error": "unknown widget"})


if __name__ == "__main__":
    unittest.main()
