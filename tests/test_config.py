import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent.config import Config


class ConfigLoadTests(unittest.TestCase):
    def test_invalid_env_values_fall_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text("{}", encoding="utf-8")

            with mock.patch.dict(
                os.environ,
                {
                    "OLLAMA_TEMPERATURE": "not-a-number",
                    "OLLAMA_NUM_CTX": "broken",
                    "WEB_PORT": "bad-port",
                    "LLAMA_CPP_AUTO_START": "not-bool",
                    "AUX_AUTONOMY_ENABLED": "invalid",
                },
                clear=False,
            ):
                cfg = Config.load(config_path)

            self.assertEqual(cfg.ollama.temperature, 0.2)
            self.assertEqual(cfg.ollama.num_ctx, 16384)
            self.assertEqual(cfg.web.port, 8080)
            self.assertFalse(cfg.llama_cpp.auto_start)
            self.assertFalse(cfg.autonomy.enabled)

    def test_valid_env_values_override_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text("{}", encoding="utf-8")

            with mock.patch.dict(
                os.environ,
                {
                    "LLM_PROVIDER": "ollama",
                    "OLLAMA_MODEL": "qwen2.5:7b",
                    "OLLAMA_TEMPERATURE": "0.7",
                    "OLLAMA_NUM_CTX": "4096",
                    "WEB_HOST": "127.0.0.1",
                    "WEB_PORT": "9090",
                    "LLAMA_CPP_AUTO_START": "true",
                    "AUX_AUTONOMY_ENABLED": "yes",
                },
                clear=False,
            ):
                cfg = Config.load(config_path)

            self.assertEqual(cfg.agent.provider, "ollama")
            self.assertEqual(cfg.ollama.model, "qwen2.5:7b")
            self.assertEqual(cfg.ollama.temperature, 0.7)
            self.assertEqual(cfg.ollama.num_ctx, 4096)
            self.assertEqual(cfg.web.host, "127.0.0.1")
            self.assertEqual(cfg.web.port, 9090)
            self.assertTrue(cfg.llama_cpp.auto_start)
            self.assertTrue(cfg.autonomy.enabled)
