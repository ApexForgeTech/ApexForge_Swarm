from __future__ import annotations

from typing import List

from ..tools.base import BaseTool


class PluginTool(BaseTool):
    """
    Base class for dynamically-loaded plugin tools.

    Subclass this in any *.py file inside the plugins/ directory.
    The loader will discover, instantiate, and register it automatically.

    Required class attributes (inherit from BaseTool):
      name        — unique snake_case identifier (e.g. "my_tool")
      description — one-sentence description shown to the LLM
      parameters  — JSON Schema dict for the tool's arguments

    Optional class attributes:
      version — semver string, default "1.0.0"
      author  — plugin author name
      tags    — list of topic tags for /api/plugins filtering
    """

    version: str = "1.0.0"
    author: str = ""
    tags: List[str] = []

    def plugin_metadata(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "tags": list(self.tags),
        }
