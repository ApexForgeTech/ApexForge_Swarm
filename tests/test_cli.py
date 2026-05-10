import os
import unittest
from unittest import mock

from agent.config import Config
from cli import _cli_backend_preflight_enabled, _env_truthy, _llama_cpp_target


class CliHelpersTests(unittest.TestCase):
    def test_env_truthy_accepts_common_true_values(self):
        with mock.patch.dict(os.environ, {"APEXFORGE_CLI_BACKEND_PREFLIGHT": "true"}, clear=False):
            self.assertTrue(_env_truthy("APEXFORGE_CLI_BACKEND_PREFLIGHT"))

    def test_llama_cpp_target_reads_custom_port(self):
        cfg = Config()
        cfg.llama_cpp.host = "http://127.0.0.1:9091"
        self.assertEqual(_llama_cpp_target(cfg), "127.0.0.1:9091")

    def test_cli_backend_preflight_requires_llama_cpp_and_env(self):
        cfg = Config()
        cfg.agent.provider = "llama_cpp"
        with mock.patch.dict(os.environ, {"APEXFORGE_CLI_BACKEND_PREFLIGHT": "1"}, clear=False):
            self.assertTrue(_cli_backend_preflight_enabled(cfg))

        cfg.agent.provider = "ollama"
        with mock.patch.dict(os.environ, {"APEXFORGE_CLI_BACKEND_PREFLIGHT": "1"}, clear=False):
            self.assertFalse(_cli_backend_preflight_enabled(cfg))
