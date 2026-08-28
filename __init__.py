"""ComfyUI custom-node entrypoint for the ComfyUI-AIAssistant extension.

ComfyUI imports this file when the repository directory is installed under
``custom_nodes``. It registers the backend context routes once and exports the
standard extension constants.
"""

from __future__ import annotations

from .ai_assistant.server import register_routes

register_routes()

WEB_DIRECTORY = "./web"

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
