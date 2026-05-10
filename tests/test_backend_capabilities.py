import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent.config import Config
from agent.llm_backend import get_backend_capabilities


class BackendCapabilitiesTests(unittest.TestCase):
    def _load_config(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        config_path = Path(tmpdir.name) / "config.yaml"
        config_path.write_text("{}", encoding="utf-8")
        return Config.load(config_path)

    def test_llama_cpp_capabilities_explain_serialized_multi_agent_rules(self):
        cfg = self._load_config()
        cfg.agent.provider = "llama_cpp"
        cfg.llama_cpp.auto_start = True

        capabilities = get_backend_capabilities(cfg).as_dict()

        self.assertEqual(capabilities["provider"], "llama_cpp")
        self.assertTrue(capabilities["multi_agent_supported"])
        self.assertEqual(capabilities["request_parallelism"], "serialized")
        self.assertEqual(capabilities["mixed_model_missions"], "normalized_to_single_model")
        self.assertTrue(capabilities["auto_start_supported"])
        self.assertTrue(any("single active-model server" in note for note in capabilities["notes"]))

    def test_ollama_capabilities_change_when_serialization_env_is_enabled(self):
        cfg = self._load_config()
        cfg.agent.provider = "ollama"

        with mock.patch.dict(os.environ, {"APEXFORGE_SERIALIZE_LLM_REQUESTS": "true"}, clear=False):
            capabilities = get_backend_capabilities(cfg).as_dict()

        self.assertEqual(capabilities["provider"], "ollama")
        self.assertEqual(capabilities["request_parallelism"], "serialized")
        self.assertEqual(capabilities["mixed_model_missions"], "supported")
        self.assertTrue(any("serialization" in note.lower() for note in capabilities["notes"]))
