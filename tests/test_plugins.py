"""Tests for the plugin system (agent/plugins/)."""
import tempfile
import unittest
from pathlib import Path

from agent.plugins import PluginLoader, PluginLoadResult, PluginTool


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_plugin(directory: Path, filename: str, source: str) -> Path:
    path = directory / filename
    path.write_text(source, encoding="utf-8")
    return path


VALID_PLUGIN_SRC = """
from agent.plugins import PluginTool

class EchoTool(PluginTool):
    name = "echo"
    description = "Echoes the input back."
    version = "1.2.3"
    author = "Tester"
    tags = ["test"]
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def execute(self, text: str = "") -> str:
        return text
"""

TWO_TOOLS_SRC = """
from agent.plugins import PluginTool

class ToolA(PluginTool):
    name = "tool_a"
    description = "Tool A"
    parameters = {}
    def execute(self, **kwargs) -> str:
        return "A"

class ToolB(PluginTool):
    name = "tool_b"
    description = "Tool B"
    parameters = {}
    def execute(self, **kwargs) -> str:
        return "B"
"""

NO_NAME_SRC = """
from agent.plugins import PluginTool

class NoNameTool(PluginTool):
    name = ""
    description = "Missing name"
    parameters = {}
    def execute(self, **kwargs) -> str:
        return ""
"""

SYNTAX_ERROR_SRC = "def bad syntax!!!"

NOT_A_PLUGIN_SRC = """
class RandomClass:
    pass
"""


# ── PluginTool base ───────────────────────────────────────────────────────────

class PluginToolBaseTests(unittest.TestCase):
    def test_plugin_metadata_returns_expected_fields(self):
        class MyTool(PluginTool):
            name = "my_tool"
            description = "does stuff"
            version = "2.0.0"
            author = "Alice"
            tags = ["a", "b"]
            parameters = {}
            def execute(self, **kwargs): return ""

        tool = MyTool()
        meta = tool.plugin_metadata()
        self.assertEqual(meta["name"], "my_tool")
        self.assertEqual(meta["description"], "does stuff")
        self.assertEqual(meta["version"], "2.0.0")
        self.assertEqual(meta["author"], "Alice")
        self.assertEqual(meta["tags"], ["a", "b"])

    def test_plugin_tool_is_abstract_without_execute(self):
        class BadTool(PluginTool):
            name = "bad"
            description = "no execute"
            parameters = {}

        with self.assertRaises(TypeError):
            BadTool()

    def test_to_ollama_schema_includes_function_block(self):
        class SomeTool(PluginTool):
            name = "some_tool"
            description = "A tool"
            parameters = {"type": "object", "properties": {}, "required": []}
            def execute(self, **kwargs): return ""

        schema = SomeTool().to_ollama_schema()
        self.assertEqual(schema["type"], "function")
        self.assertEqual(schema["function"]["name"], "some_tool")


# ── PluginLoader ──────────────────────────────────────────────────────────────

class PluginLoaderTests(unittest.TestCase):
    def _tmpdir(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return Path(d.name)

    def test_load_valid_plugin(self):
        d = self._tmpdir()
        _write_plugin(d, "echo_plugin.py", VALID_PLUGIN_SRC)
        result = PluginLoader(d).load()
        self.assertEqual(len(result.loaded), 1)
        self.assertEqual(result.loaded[0].name, "echo")
        self.assertEqual(result.errors, [])

    def test_loaded_plugin_execute_works(self):
        d = self._tmpdir()
        _write_plugin(d, "echo_plugin.py", VALID_PLUGIN_SRC)
        result = PluginLoader(d).load()
        output = result.loaded[0].execute(text="hello world")
        self.assertEqual(output, "hello world")

    def test_plugin_metadata_preserved(self):
        d = self._tmpdir()
        _write_plugin(d, "echo_plugin.py", VALID_PLUGIN_SRC)
        result = PluginLoader(d).load()
        meta = result.loaded[0].plugin_metadata()
        self.assertEqual(meta["version"], "1.2.3")
        self.assertEqual(meta["author"], "Tester")
        self.assertEqual(meta["tags"], ["test"])

    def test_load_two_tools_from_one_file(self):
        d = self._tmpdir()
        _write_plugin(d, "multi.py", TWO_TOOLS_SRC)
        result = PluginLoader(d).load()
        names = {t.name for t in result.loaded}
        self.assertIn("tool_a", names)
        self.assertIn("tool_b", names)

    def test_private_files_skipped(self):
        d = self._tmpdir()
        _write_plugin(d, "_private.py", VALID_PLUGIN_SRC)
        result = PluginLoader(d).load()
        self.assertEqual(result.loaded, [])
        self.assertIn("_private.py", result.skipped)

    def test_file_with_no_plugin_tools_skipped(self):
        d = self._tmpdir()
        _write_plugin(d, "random_module.py", NOT_A_PLUGIN_SRC)
        result = PluginLoader(d).load()
        self.assertEqual(result.loaded, [])
        self.assertIn("random_module.py", result.skipped)

    def test_syntax_error_goes_to_errors_not_crash(self):
        d = self._tmpdir()
        _write_plugin(d, "broken.py", SYNTAX_ERROR_SRC)
        result = PluginLoader(d).load()
        self.assertEqual(result.loaded, [])
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0][0], "broken.py")

    def test_missing_name_goes_to_errors(self):
        d = self._tmpdir()
        _write_plugin(d, "no_name.py", NO_NAME_SRC)
        result = PluginLoader(d).load()
        self.assertEqual(result.loaded, [])
        self.assertEqual(len(result.errors), 1)

    def test_bad_plugin_does_not_prevent_good_plugin_from_loading(self):
        d = self._tmpdir()
        _write_plugin(d, "aaa_broken.py", SYNTAX_ERROR_SRC)
        _write_plugin(d, "bbb_good.py", VALID_PLUGIN_SRC)
        result = PluginLoader(d).load()
        self.assertEqual(len(result.loaded), 1)
        self.assertEqual(len(result.errors), 1)

    def test_empty_directory_returns_empty_result(self):
        d = self._tmpdir()
        result = PluginLoader(d).load()
        self.assertEqual(result.loaded, [])
        self.assertEqual(result.errors, [])

    def test_nonexistent_directory_returns_empty_result(self):
        result = PluginLoader("/nonexistent/path/plugins").load()
        self.assertEqual(result.loaded, [])
        self.assertEqual(result.errors, [])

    def test_discover_lists_candidate_files(self):
        d = self._tmpdir()
        _write_plugin(d, "tool_one.py", VALID_PLUGIN_SRC)
        _write_plugin(d, "_private.py", VALID_PLUGIN_SRC)
        candidates = PluginLoader(d).discover()
        self.assertIn("tool_one.py", candidates)
        self.assertNotIn("_private.py", candidates)

    def test_discover_empty_on_missing_dir(self):
        self.assertEqual(PluginLoader("/no/such/dir").discover(), [])

    def test_load_result_as_dict(self):
        d = self._tmpdir()
        _write_plugin(d, "echo_plugin.py", VALID_PLUGIN_SRC)
        _write_plugin(d, "_skip.py", VALID_PLUGIN_SRC)
        result = PluginLoader(d).load()
        d_result = result.as_dict()
        self.assertIn("echo", d_result["loaded"])
        self.assertIn("_skip.py", d_result["skipped"])
        self.assertEqual(d_result["errors"], [])

    def test_multiple_files_all_loaded(self):
        d = self._tmpdir()
        for i in range(4):
            _write_plugin(d, f"tool_{i}.py", VALID_PLUGIN_SRC.replace('"echo"', f'"echo_{i}"').replace("EchoTool", f"EchoTool{i}"))
        result = PluginLoader(d).load()
        self.assertEqual(len(result.loaded), 4)


# ── Bundled example plugins ───────────────────────────────────────────────────

class BundledPluginTests(unittest.TestCase):
    PLUGINS_DIR = Path(__file__).parent.parent / "plugins"

    def test_datetime_tool_loads(self):
        result = PluginLoader(self.PLUGINS_DIR).load()
        names = {t.name for t in result.loaded}
        self.assertIn("get_datetime", names)

    def test_word_counter_tool_loads(self):
        result = PluginLoader(self.PLUGINS_DIR).load()
        names = {t.name for t in result.loaded}
        self.assertIn("word_count", names)

    def test_datetime_tool_returns_string(self):
        result = PluginLoader(self.PLUGINS_DIR).load()
        tool = next(t for t in result.loaded if t.name == "get_datetime")
        output = tool.execute(tz="utc")
        self.assertIsInstance(output, str)
        self.assertRegex(output, r"\d{4}-\d{2}-\d{2}")

    def test_word_counter_tool_counts_correctly(self):
        result = PluginLoader(self.PLUGINS_DIR).load()
        tool = next(t for t in result.loaded if t.name == "word_count")
        output = tool.execute(text="hello world\nfoo bar baz")
        self.assertIn("Words: 5", output)
        self.assertIn("Lines: 2", output)

    def test_no_errors_in_bundled_plugins(self):
        result = PluginLoader(self.PLUGINS_DIR).load()
        self.assertEqual(result.errors, [], msg=f"Plugin errors: {result.errors}")
