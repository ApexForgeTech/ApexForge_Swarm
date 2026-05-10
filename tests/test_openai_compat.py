import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from agent.config import Config, OpenAICompatConfig
from agent.llm_backend import (
    OpenAICompatBackend,
    create_llm_backend,
    detect_available_backends,
    LLMChunk,
    OllamaBackend,
    LlamaCppBackend,
)


class OpenAICompatConfigTests(unittest.TestCase):
    def test_defaults(self):
        cfg = OpenAICompatConfig()
        self.assertEqual(cfg.base_url, "")
        self.assertEqual(cfg.model, "gpt-4o-mini")
        self.assertEqual(cfg.max_tokens, 4096)
        self.assertEqual(cfg.request_timeout, 120)

    def test_env_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text("{}", encoding="utf-8")
            with mock.patch.dict(
                os.environ,
                {
                    "OPENAI_COMPAT_BASE_URL": "https://api.groq.com/openai/v1",
                    "OPENAI_COMPAT_API_KEY": "gsk_test",
                    "OPENAI_COMPAT_MODEL": "llama-3.3-70b-versatile",
                    "OPENAI_COMPAT_MAX_TOKENS": "8192",
                    "OPENAI_COMPAT_REQUEST_TIMEOUT": "60",
                },
                clear=False,
            ):
                cfg = Config.load(config_path)

        self.assertEqual(cfg.openai_compat.base_url, "https://api.groq.com/openai/v1")
        self.assertEqual(cfg.openai_compat.api_key, "gsk_test")
        self.assertEqual(cfg.openai_compat.model, "llama-3.3-70b-versatile")
        self.assertEqual(cfg.openai_compat.max_tokens, 8192)
        self.assertEqual(cfg.openai_compat.request_timeout, 60)

    def test_openai_api_key_fallback(self):
        """OPENAI_API_KEY da qəbul edilir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text("{}", encoding="utf-8")
            with mock.patch.dict(
                os.environ,
                {"OPENAI_API_KEY": "sk-fallback-key"},
                clear=False,
            ):
                with mock.patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("OPENAI_COMPAT_API_KEY", None)
                    cfg = Config.load(config_path)

        self.assertEqual(cfg.openai_compat.api_key, "sk-fallback-key")

    def test_config_round_trip(self):
        """Config save/load dövrü openai_compat-ı qoruyur."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.yaml"
            cfg = Config()
            cfg.openai_compat.base_url = "https://api.groq.com/openai/v1"
            cfg.openai_compat.model = "llama-3.1-8b-instant"
            cfg.openai_compat.max_tokens = 2048
            cfg.save(path)

            loaded = Config.load(path)

        self.assertEqual(loaded.openai_compat.base_url, "https://api.groq.com/openai/v1")
        self.assertEqual(loaded.openai_compat.model, "llama-3.1-8b-instant")
        self.assertEqual(loaded.openai_compat.max_tokens, 2048)


class BackendFactoryTests(unittest.TestCase):
    def _config_with_provider(self, provider: str) -> Config:
        cfg = Config()
        cfg.agent.provider = provider
        return cfg

    def test_factory_ollama(self):
        backend = create_llm_backend(self._config_with_provider("ollama"))
        self.assertIsInstance(backend, OllamaBackend)

    def test_factory_llama_cpp(self):
        backend = create_llm_backend(self._config_with_provider("llama_cpp"))
        self.assertIsInstance(backend, LlamaCppBackend)

    def test_factory_openai_compat(self):
        backend = create_llm_backend(self._config_with_provider("openai_compat"))
        self.assertIsInstance(backend, OpenAICompatBackend)

    def test_factory_unknown_falls_back_to_ollama(self):
        backend = create_llm_backend(self._config_with_provider("unknown_provider_xyz"))
        self.assertIsInstance(backend, OllamaBackend)


class LlamaCppBackendTransientReadinessTests(unittest.TestCase):
    def _backend(self) -> LlamaCppBackend:
        cfg = Config()
        cfg.agent.provider = "llama_cpp"
        return LlamaCppBackend(cfg)

    def test_loading_model_503_is_treated_as_transient_models_wait(self):
        backend = self._backend()
        self.assertTrue(
            backend._is_transient_models_http_error(
                "GET",
                "/v1/models",
                503,
                '{"error":{"message":"Loading model","type":"unavailable_error","code":503}}',
            )
        )

    def test_connection_refused_on_models_ping_is_treated_as_transient(self):
        backend = self._backend()
        self.assertTrue(
            backend._is_transient_models_url_error(
                "GET",
                "/v1/models",
                "[Errno 111] Connection refused",
            )
        )

    def test_non_models_http_error_is_not_treated_as_transient(self):
        backend = self._backend()
        self.assertFalse(
            backend._is_transient_models_http_error(
                "POST",
                "/v1/chat/completions",
                503,
                '{"error":{"message":"Loading model"}}',
            )
        )


class OpenAICompatBackendCapabilitiesTests(unittest.TestCase):
    def _backend(self, base_url: str = "") -> OpenAICompatBackend:
        cfg = Config()
        cfg.openai_compat.base_url = base_url
        return OpenAICompatBackend(cfg)

    def test_capabilities_official(self):
        caps = self._backend("").capabilities()
        self.assertEqual(caps.provider, "openai_compat")
        self.assertTrue(caps.multi_agent_supported)
        self.assertEqual(caps.request_parallelism, "parallel")
        self.assertEqual(caps.mixed_model_missions, "supported")
        self.assertFalse(caps.auto_start_supported)
        self.assertFalse(caps.local_model_discovery)

    def test_capabilities_groq_hint(self):
        caps = self._backend("https://api.groq.com/openai/v1").capabilities()
        self.assertTrue(any("groq" in note for note in caps.notes))

    def test_active_model_fallback(self):
        cfg = Config()
        cfg.openai_compat.model = ""
        cfg.ollama.model = "qwen2.5:7b"
        backend = OpenAICompatBackend(cfg)
        self.assertEqual(backend._active_model(), "qwen2.5:7b")

    def test_active_model_preferred(self):
        cfg = Config()
        cfg.openai_compat.model = "gpt-4o"
        cfg.ollama.model = "qwen2.5:7b"
        backend = OpenAICompatBackend(cfg)
        self.assertEqual(backend._active_model(), "gpt-4o")


class OpenAICompatBackendChatTests(unittest.TestCase):
    def _backend(self) -> OpenAICompatBackend:
        cfg = Config()
        cfg.openai_compat.api_key = "sk-test"
        cfg.openai_compat.model = "gpt-4o-mini"
        return OpenAICompatBackend(cfg)

    def test_missing_openai_package_raises(self):
        backend = self._backend()
        with mock.patch.dict("sys.modules", {"openai": None}):
            with self.assertRaises(RuntimeError) as ctx:
                backend._client()
        self.assertIn("openai paketi", str(ctx.exception))

    def test_chat_stream_no_tools_uses_streaming(self):
        """Tool yoxdursa streaming path işlənir."""
        backend = self._backend()

        fake_chunk = mock.MagicMock()
        fake_chunk.choices = [mock.MagicMock()]
        fake_chunk.choices[0].delta.content = "Hello"

        fake_stream = iter([fake_chunk])

        mock_completions = mock.MagicMock()
        mock_completions.create.return_value = fake_stream

        mock_client = mock.MagicMock()
        mock_client.chat.completions = mock_completions

        with mock.patch.object(backend, "_client", return_value=mock_client):
            chunks = list(backend.chat_stream([{"role": "user", "content": "hi"}]))

        call_kwargs = mock_completions.create.call_args[1]
        self.assertTrue(call_kwargs.get("stream"), "stream=True beklənirdi")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].content, "Hello")

    def test_chat_stream_with_tools_uses_batch(self):
        """Tool varsa stream=False (batch) path işlənir."""
        backend = self._backend()

        fake_msg = mock.MagicMock()
        fake_msg.content = "I will call a tool"
        fake_msg.tool_calls = []
        fake_resp = mock.MagicMock()
        fake_resp.choices = [mock.MagicMock()]
        fake_resp.choices[0].message = fake_msg

        mock_completions = mock.MagicMock()
        mock_completions.create.return_value = fake_resp

        mock_client = mock.MagicMock()
        mock_client.chat.completions = mock_completions

        tools = [{"type": "function", "function": {"name": "test_tool"}}]
        with mock.patch.object(backend, "_client", return_value=mock_client):
            chunks = list(backend.chat_stream(
                [{"role": "user", "content": "use tool"}],
                tools=tools,
            ))

        call_kwargs = mock_completions.create.call_args[1]
        self.assertNotIn("stream", call_kwargs)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].content, "I will call a tool")

    def test_parse_openai_tool_calls(self):
        backend = self._backend()

        tc = mock.MagicMock()
        tc.id = "call_abc123"
        tc.function.name = "read_file"
        tc.function.arguments = '{"path": "/tmp/test.txt"}'

        result = backend._parse_openai_tool_calls([tc])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "call_abc123")
        self.assertEqual(result[0].function.name, "read_file")
        self.assertEqual(result[0].function.arguments, {"path": "/tmp/test.txt"})

    def test_list_models_fallback_on_error(self):
        backend = self._backend()

        mock_client = mock.MagicMock()
        mock_client.models.list.side_effect = Exception("API unreachable")

        with mock.patch.object(backend, "_client", return_value=mock_client):
            models = backend.list_models()

        self.assertIsInstance(models, list)
        self.assertGreater(len(models), 0)


class DetectBackendsTests(unittest.TestCase):
    def test_returns_list_of_dicts(self):
        cfg = Config()
        result = detect_available_backends(cfg)
        self.assertIsInstance(result, list)
        providers = [r["provider"] for r in result]
        self.assertIn("ollama", providers)
        self.assertIn("llama_cpp", providers)
        self.assertIn("openai_compat", providers)

    def test_openai_compat_not_configured_when_no_key(self):
        cfg = Config()
        cfg.openai_compat.api_key = ""
        result = detect_available_backends(cfg)
        oc = next(r for r in result if r["provider"] == "openai_compat")
        self.assertEqual(oc["status"], "not_configured")

    def test_ollama_unreachable_when_wrong_host(self):
        cfg = Config()
        cfg.ollama.host = "http://127.0.0.1:19999"
        result = detect_available_backends(cfg)
        ollama = next(r for r in result if r["provider"] == "ollama")
        self.assertIn(ollama["status"], {"unreachable", "package_missing"})
