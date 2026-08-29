"""Contract tests for pure command validation and result shaping.

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
_MODULE_NAME = "_ai_assistant_commands_test"


def _load_module():
    path = _REPO_ROOT / "ai_assistant" / "commands.py"
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


COMMANDS = _load_module()

TEXT_WIDGET = {"name": "text", "type": "text", "value": "hello"}
CUSTOMTEXT_WIDGET = {"name": "prompt", "type": "customtext", "value": ""}
STRING_WIDGET = {"name": "name", "type": "string", "value": ""}
NUMBER_WIDGET = {"name": "cfg", "type": "number", "value": 1}
COMBO_WIDGET = {"name": "sampler", "type": "combo", "value": "euler"}


def _envelope(snapshot: Any = None) -> dict[str, Any]:
    return {
        "schema_version": "comfyui.ai-assistant.context/1",
        "available": snapshot is not None,
        "received_at": "2026-08-29T10:00:00+00:00",
        "snapshot": snapshot,
    }


def _snapshot(
    *,
    revision: int = 7,
    selection_detail: str = "full",
    selected_count: Any = None,
    widgets: Any = (),
) -> dict[str, Any]:
    selection: list[dict[str, Any]] = []
    if widgets is not None:
        selection = [{"id": 3, "title": "KSampler", "widgets": list(widgets)}]
    return {
        "schema_version": "comfyui.ai-assistant.context/1",
        "captured_at": "2026-08-29T10:00:00+00:00",
        "revision": revision,
        "workflow": {
            "id": 3,
            "title": "KSampler",
            "selection_detail": selection_detail,
            "selected_count": selected_count,
        },
        "selection": selection,
    }


class ValidateParamsTests(unittest.TestCase):
    def test_accepts_valid_params(self):
        result = COMMANDS.validate_params(
            {"widget": "text", "text": "hello", "expected_revision": 7}
        )
        self.assertEqual(
            result,
            {"ok": True, "widget": "text", "text": "hello", "expected_revision": 7},
        )

    def test_rejects_non_dict_params(self):
        for params in ("x", [1], 3, None, True):
            with self.subTest(params=params):
                self.assertEqual(
                    COMMANDS.validate_params(params),
                    {"ok": False, "error": "invalid params shape"},
                )

    def test_rejects_extra_key(self):
        result = COMMANDS.validate_params(
            {"widget": "text", "text": "hi", "expected_revision": 0, "extra": 1}
        )
        self.assertEqual(result, {"ok": False, "error": "invalid params keys"})

    def test_rejects_missing_key(self):
        for params in (
            {"widget": "text", "text": "hi"},
            {"widget": "text", "expected_revision": 0},
            {"text": "hi", "expected_revision": 0},
            {},
        ):
            with self.subTest(params=params):
                self.assertEqual(
                    COMMANDS.validate_params(params),
                    {"ok": False, "error": "invalid params keys"},
                )

    def test_rejects_non_string_widget(self):
        for widget in (3, 3.5, None, True, ["text"], {"n": "x"}):
            with self.subTest(widget=widget):
                result = COMMANDS.validate_params(
                    {"widget": widget, "text": "hi", "expected_revision": 0}
                )
                self.assertEqual(result, {"ok": False, "error": "invalid widget name"})

    def test_rejects_empty_widget_name(self):
        result = COMMANDS.validate_params({"widget": "", "text": "hi", "expected_revision": 0})
        self.assertEqual(result, {"ok": False, "error": "invalid widget name"})

    def test_rejects_oversized_widget_name(self):
        result = COMMANDS.validate_params(
            {
                "widget": "x" * (COMMANDS.MAX_WIDGET_NAME_LENGTH + 1),
                "text": "hi",
                "expected_revision": 0,
            }
        )
        self.assertEqual(result, {"ok": False, "error": "invalid widget name"})

    def test_accepts_boundary_widget_name_lengths(self):
        for length in (1, COMMANDS.MAX_WIDGET_NAME_LENGTH):
            with self.subTest(length=length):
                result = COMMANDS.validate_params(
                    {"widget": "x" * length, "text": "hi", "expected_revision": 0}
                )
                self.assertIs(result["ok"], True)

    def test_rejects_non_string_text(self):
        for text in (3, 3.5, None, True, ["hi"], {"n": "x"}):
            with self.subTest(text=text):
                result = COMMANDS.validate_params(
                    {"widget": "text", "text": text, "expected_revision": 0}
                )
                self.assertEqual(result, {"ok": False, "error": "invalid text"})

    def test_rejects_oversized_text(self):
        result = COMMANDS.validate_params(
            {
                "widget": "text",
                "text": "x" * (COMMANDS.MAX_TEXT_LENGTH + 1),
                "expected_revision": 0,
            }
        )
        self.assertEqual(result, {"ok": False, "error": "invalid text"})

    def test_accepts_empty_and_max_length_text(self):
        for text in ("", "x" * COMMANDS.MAX_TEXT_LENGTH):
            with self.subTest(length=len(text)):
                result = COMMANDS.validate_params(
                    {"widget": "text", "text": text, "expected_revision": 0}
                )
                self.assertIs(result["ok"], True)
                self.assertEqual(result["text"], text)

    def test_rejects_bool_revision(self):
        for revision in (True, False):
            with self.subTest(revision=revision):
                result = COMMANDS.validate_params(
                    {"widget": "text", "text": "hi", "expected_revision": revision}
                )
                self.assertEqual(result, {"ok": False, "error": "invalid expected revision"})

    def test_rejects_non_int_revision(self):
        for revision in ("3", 3.5, None, [], {"n": 1}):
            with self.subTest(revision=revision):
                result = COMMANDS.validate_params(
                    {"widget": "text", "text": "hi", "expected_revision": revision}
                )
                self.assertEqual(result, {"ok": False, "error": "invalid expected revision"})

    def test_rejects_negative_revision(self):
        result = COMMANDS.validate_params({"widget": "text", "text": "hi", "expected_revision": -1})
        self.assertEqual(result, {"ok": False, "error": "invalid expected revision"})

    def test_accepts_zero_and_positive_revision(self):
        for revision in (0, 7, 2**63):
            with self.subTest(revision=revision):
                result = COMMANDS.validate_params(
                    {"widget": "text", "text": "hi", "expected_revision": revision}
                )
                self.assertIs(result["ok"], True)
                self.assertEqual(result["expected_revision"], revision)


class ResolveSelectionTests(unittest.TestCase):
    def test_unavailable_snapshot(self):
        result = COMMANDS.resolve_selection(_envelope(), "text")
        self.assertEqual(result, {"ok": False, "error": "no selection available"})

    def test_names_only_selection_detail(self):
        envelope = _envelope(_snapshot(selection_detail="names_only"))
        result = COMMANDS.resolve_selection(envelope, "text")
        self.assertEqual(result, {"ok": False, "error": "multiple nodes selected"})

    def test_empty_selection_none_detail(self):
        envelope = _envelope(_snapshot(selection_detail="none", selected_count=0, widgets=None))
        result = COMMANDS.resolve_selection(envelope, "text")
        self.assertEqual(result, {"ok": False, "error": "no node selected"})

    def test_empty_selection_zero_count_full_detail(self):
        envelope = _envelope(_snapshot(selected_count=0))
        result = COMMANDS.resolve_selection(envelope, "text")
        self.assertEqual(result, {"ok": False, "error": "no node selected"})

    def test_full_detail_with_empty_selection_list(self):
        envelope = _envelope(_snapshot(widgets=None))
        result = COMMANDS.resolve_selection(envelope, "text")
        self.assertEqual(result, {"ok": False, "error": "no node selected"})

    def test_full_without_widget(self):
        envelope = _envelope(_snapshot(widgets=[NUMBER_WIDGET, COMBO_WIDGET]))
        result = COMMANDS.resolve_selection(envelope, "missing")
        self.assertEqual(result, {"ok": False, "error": "unknown widget"})

    def test_full_with_non_text_widget(self):
        envelope = _envelope(_snapshot(widgets=[NUMBER_WIDGET]))
        result = COMMANDS.resolve_selection(envelope, "cfg")
        self.assertEqual(result, {"ok": False, "error": "widget is not text-like"})

    def test_full_with_matching_text_widget(self):
        envelope = _envelope(_snapshot(widgets=[NUMBER_WIDGET, TEXT_WIDGET]))
        result = COMMANDS.resolve_selection(envelope, "text")
        self.assertEqual(result, {"ok": True})

    def test_full_with_matching_customtext_widget(self):
        envelope = _envelope(_snapshot(widgets=[CUSTOMTEXT_WIDGET]))
        result = COMMANDS.resolve_selection(envelope, "prompt")
        self.assertEqual(result, {"ok": True})

    def test_full_with_matching_string_widget(self):
        envelope = _envelope(_snapshot(widgets=[STRING_WIDGET]))
        result = COMMANDS.resolve_selection(envelope, "name")
        self.assertEqual(result, {"ok": True})


class CheckRevisionTests(unittest.TestCase):
    def test_matching_revision(self):
        envelope = _envelope(_snapshot(revision=7))
        self.assertEqual(COMMANDS.check_revision(envelope, 7), {"ok": True})

    def test_mismatch_reports_current_revision(self):
        envelope = _envelope(_snapshot(revision=7))
        self.assertEqual(
            COMMANDS.check_revision(envelope, 5),
            {"ok": False, "error": "revision mismatch", "current_revision": 7},
        )

    def test_no_snapshot_fails_with_same_shape(self):
        result = COMMANDS.check_revision(_envelope(), 0)
        self.assertEqual(
            result,
            {"ok": False, "error": "revision mismatch", "current_revision": None},
        )


class SuccessResultTests(unittest.TestCase):
    def test_applied_result_exact_text(self):
        result = COMMANDS.success_result("applied", 8, "text")
        self.assertEqual(
            result,
            {
                "content": [
                    {
                        "type": "text",
                        "text": '{"status":"applied","revision":8,"widget":"text"}',
                    }
                ],
                "isError": False,
            },
        )

    def test_queued_result_exact_text(self):
        result = COMMANDS.success_result("queued", 7, "prompt")
        self.assertEqual(
            result["content"][0]["text"],
            json.dumps(
                {"status": "queued", "revision": 7, "widget": "prompt"},
                separators=(",", ":"),
            ),
        )
        self.assertIs(result["isError"], False)


class FailureResultTests(unittest.TestCase):
    def test_error_without_current_revision(self):
        result = COMMANDS.failure_result("no selection available")
        self.assertEqual(
            result,
            {
                "content": [{"type": "text", "text": '{"error":"no selection available"}'}],
                "isError": True,
            },
        )

    def test_error_with_current_revision(self):
        result = COMMANDS.failure_result("revision mismatch", 7)
        self.assertEqual(
            result["content"][0]["text"],
            '{"error":"revision mismatch","current_revision":7}',
        )
        self.assertIs(result["isError"], True)

    def test_default_current_revision_is_omitted(self):
        result = COMMANDS.failure_result("some error")
        self.assertEqual(
            json.loads(result["content"][0]["text"]),
            {"error": "some error"},
        )


class BuildCommandTests(unittest.TestCase):
    def test_command_frame_shape(self):
        result = COMMANDS.build_command("cmd-1", "text", "hello")
        self.assertEqual(
            result,
            {
                "type": "command",
                "command_id": "cmd-1",
                "op": "set_widget_text",
                "widget": "text",
                "text": "hello",
            },
        )

    def test_empty_text_round_trips(self):
        result = COMMANDS.build_command("cmd-2", "prompt", "")
        self.assertEqual(result["op"], "set_widget_text")
        self.assertEqual(result["text"], "")


if __name__ == "__main__":
    unittest.main()
