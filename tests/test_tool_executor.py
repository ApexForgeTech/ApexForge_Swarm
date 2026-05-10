import logging
import unittest

from agent.tool_executor import ToolExecutor


class ToolExecutorTests(unittest.TestCase):
    def setUp(self):
        self.executor = ToolExecutor({}, logging.getLogger("test_tool_executor"))

    def test_is_tool_error_detects_python_syntax_error_stderr(self):
        result = (
            "[stderr]\n"
            "  File \"<string>\", line 2\n"
            "    print(\n"
            "         ^\n"
            "SyntaxError: '(' was never closed\n"
            "[exit code: 1]"
        )
        self.assertTrue(self.executor.is_tool_error(result))

    def test_is_tool_error_detects_nonzero_exit_code_without_traceback(self):
        result = "[stderr]\nsome stderr\n[exit code: 2]"
        self.assertTrue(self.executor.is_tool_error(result))

    def test_augment_error_result_adds_recovery_hint_for_python_syntax_error(self):
        result = (
            "[stderr]\n"
            "SyntaxError: unterminated string literal (detected at line 7)\n"
            "[exit code: 1]"
        )
        augmented = self.executor._augment_error_result("run_python", result)
        self.assertIn("syntactically invalid", augmented)
        self.assertIn("write_file", augmented)
