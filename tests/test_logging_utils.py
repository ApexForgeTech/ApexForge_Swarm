import io
import logging
import unittest

from agent.logging_utils import ApexSwarmFormatter, log_event


class StructuredLoggingTests(unittest.TestCase):
    def test_text_formatter_includes_event_and_fields(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(ApexSwarmFormatter(json_mode=False))
        logger = logging.getLogger("tests.logging.text")
        logger.handlers = []
        logger.propagate = False
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        log_event(logger, logging.INFO, "mission_started", provider="ollama", worker_count=2)

        output = stream.getvalue()
        self.assertIn("mission_started", output)
        self.assertIn('provider="ollama"', output)
        self.assertIn("worker_count=2", output)

    def test_json_formatter_outputs_machine_readable_payload(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(ApexSwarmFormatter(json_mode=True))
        logger = logging.getLogger("tests.logging.json")
        logger.handlers = []
        logger.propagate = False
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        log_event(logger, logging.INFO, "tool_call_completed", tool="read_file", result_preview="hello")

        output = stream.getvalue()
        self.assertIn('"event": "tool_call_completed"', output)
        self.assertIn('"tool": "read_file"', output)
        self.assertIn('"logger": "tests.logging.json"', output)
