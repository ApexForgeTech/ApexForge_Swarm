import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import agent.web.app as web_app
from agent.config import Config


class _FakeAgent:
    def __init__(self):
        self.messages = []
        self.memory = mock.MagicMock()
        self.memory.list_skills.return_value = []
        self.memory.list_memories.return_value = []

    def available_models(self):
        return ["demo-model"]

    def token_estimate(self):
        return 0

    def message_count(self):
        return 0

    def backend_capabilities(self):
        return {}

    def clear(self):
        return None

    def reload_memory(self):
        return None

    def chat(self, prompt, images=None):
        yield {"type": "text", "data": f"echo:{prompt}"}
        yield {"type": "done"}


class WebServeModeTests(unittest.TestCase):
    def _client(self, mode: str = "serve"):
        tmpdir = tempfile.mkdtemp()
        cfg = Config()
        cfg.agent.memory_dir = str(Path(tmpdir) / "memory")
        Path(cfg.agent.memory_dir).mkdir(parents=True, exist_ok=True)

        fake_agent = _FakeAgent()
        build_agent_patcher = mock.patch("agent.web.app.build_agent", return_value=fake_agent)
        store_patcher = mock.patch("agent.web.app.SessionStore")
        build_agent_patcher.start()
        store_patcher.start()
        self.addCleanup(build_agent_patcher.stop)
        self.addCleanup(store_patcher.stop)
        web_app.init(cfg, mode=mode)
        return TestClient(web_app.app)

    def test_root_returns_service_metadata_in_serve_mode(self):
        client = self._client(mode="serve")
        resp = client.get("/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["mode"], "serve")
        self.assertEqual(data["chat"], "/api/chat")

    def test_root_returns_html_in_web_mode(self):
        client = self._client(mode="web")
        resp = client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers.get("content-type", ""))

    def test_api_chat_returns_text_response(self):
        client = self._client(mode="serve")
        resp = client.post("/api/chat", json={"message": "please summarize this"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["response"], "echo:please summarize this")
