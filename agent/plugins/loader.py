from __future__ import annotations

import importlib.util
import inspect
import logging
from pathlib import Path
from typing import List, Tuple

from .base import PluginTool

logger = logging.getLogger("plugin_loader")
logger.addHandler(logging.NullHandler())


class PluginLoadResult:
    """Summary of a plugin scan."""

    def __init__(self) -> None:
        self.loaded: List[PluginTool] = []
        self.skipped: List[str] = []
        self.errors: List[Tuple[str, str]] = []

    @property
    def total_files(self) -> int:
        return len(self.loaded) + len(self.skipped) + len(self.errors)

    def as_dict(self) -> dict:
        return {
            "loaded": [t.name for t in self.loaded],
            "skipped": list(self.skipped),
            "errors": [{"file": f, "error": e} for f, e in self.errors],
        }


class PluginLoader:
    """
    Scans a directory for *.py files and loads PluginTool subclasses from them.

    Files whose names start with '_' are skipped (private/init modules).
    Each file is imported as an isolated module; errors in one file never
    prevent other plugins from loading.
    """

    def __init__(self, plugins_dir: str | Path) -> None:
        self.plugins_dir = Path(plugins_dir)

    def load(self) -> PluginLoadResult:
        """Scan the directory and return a PluginLoadResult."""
        result = PluginLoadResult()
        if not self.plugins_dir.exists() or not self.plugins_dir.is_dir():
            return result

        for path in sorted(self.plugins_dir.glob("*.py")):
            if path.name.startswith("_"):
                result.skipped.append(path.name)
                continue
            try:
                tools = self._load_file(path)
                if not tools:
                    result.skipped.append(path.name)
                else:
                    result.loaded.extend(tools)
                    logger.info(
                        "plugin_loaded",
                        extra={"file": path.name, "tools": [t.name for t in tools]},
                    )
            except Exception as exc:
                logger.warning(
                    "plugin_load_failed",
                    extra={"file": path.name, "error": str(exc)},
                )
                result.errors.append((path.name, str(exc)))

        return result

    def _load_file(self, path: Path) -> List[PluginTool]:
        module_name = f"_apexforge_plugin_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create module spec for {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        tools: List[PluginTool] = []
        for _attr_name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, PluginTool)
                and obj is not PluginTool
                and obj.__module__ == module_name
            ):
                instance = obj()
                if not instance.name:
                    raise ValueError(
                        f"PluginTool subclass '{obj.__name__}' in {path.name} has no 'name' attribute"
                    )
                tools.append(instance)
        return tools

    def discover(self) -> List[str]:
        """Return filenames of candidate plugin files (without loading them)."""
        if not self.plugins_dir.exists():
            return []
        return [
            p.name
            for p in sorted(self.plugins_dir.glob("*.py"))
            if not p.name.startswith("_")
        ]
