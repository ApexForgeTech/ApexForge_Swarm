import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent.config import Config
from agent.web.desktop import DesktopApp


class _FakeAgent:
    def available_models(self):
        return ["alpha.gguf", "beta.gguf"]

    def backend_capabilities(self):
        return {"provider": "llama_cpp", "request_parallelism": "serialized"}


class _FakeMAS:
    create_count = 0

    def __init__(self, _config, supervisor_data, workers_data):
        type(self).create_count += 1
        self.supervisor_data = supervisor_data
        self.workers_data = workers_data

    def chat(self, _message, interrupt=None):
        yield {"type": "info", "data": "Mission started.", "ts": "2026-01-01T00:00:00+00:00"}
        yield {"type": "final", "data": "Mission finished.", "ts": "2026-01-01T00:00:01+00:00"}


class _FakeWindow:
    def __init__(self):
        self.calls = []

    def evaluate_js(self, script: str):
        self.calls.append(script)


class _ImmediateThread:
    def __init__(self, target=None, daemon=None):
        self._target = target
        self.daemon = daemon

    def start(self):
        if self._target:
            self._target()


class DesktopBridgeTests(unittest.TestCase):
    def _load_config(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        config_path = Path(tmpdir.name) / "config.yaml"
        config_path.write_text("{}", encoding="utf-8")
        return Config.load(config_path)

    def test_get_models_merges_available_and_current_model(self):
        cfg = self._load_config()
        cfg.ollama.model = "current.gguf"

        with mock.patch("agent.web.desktop.build_agent", return_value=_FakeAgent()), mock.patch(
            "agent.web.desktop.MultiAgentSystem", _FakeMAS
        ):
            app = DesktopApp(cfg)
            models = app.get_models()
            self.assertEqual(models, ["alpha.gguf", "beta.gguf", "current.gguf"])
            self.assertEqual(app.get_backend_capabilities()["provider"], "llama_cpp")
            diagnostics = app.get_runtime_diagnostics()
            self.assertEqual(diagnostics["provider"], cfg.agent.provider)
            self.assertEqual(diagnostics["model"], "current.gguf")
            self.assertIn("backend_capabilities", diagnostics)
            self.assertIn("desktop_mode", diagnostics)
            self.assertIn("desktop_hint", diagnostics)

    def test_update_roles_blocks_changes_while_busy(self):
        cfg = self._load_config()

        with mock.patch("agent.web.desktop.build_agent", return_value=_FakeAgent()), mock.patch(
            "agent.web.desktop.MultiAgentSystem", _FakeMAS
        ):
            app = DesktopApp(cfg)
            app._busy_lock.acquire()
            try:
                result = app.update_roles({"role": "Lead"}, [{"role": "Dev"}])
            finally:
                app._busy_lock.release()

        self.assertEqual(result["status"], "error")
        self.assertIn("Mission is running", result["message"])

    def test_cancel_mission_marks_interrupt_when_busy(self):
        cfg = self._load_config()

        with mock.patch("agent.web.desktop.build_agent", return_value=_FakeAgent()), mock.patch(
            "agent.web.desktop.MultiAgentSystem", _FakeMAS
        ):
            app = DesktopApp(cfg)
            app._busy_lock.acquire()
            try:
                result = app.cancel_mission()
            finally:
                app._busy_lock.release()

        self.assertEqual(result["status"], "cancelling")
        self.assertTrue(app._interrupt_event.is_set())

    def test_send_message_emits_events_through_window_bridge(self):
        cfg = self._load_config()

        with mock.patch("agent.web.desktop.build_agent", return_value=_FakeAgent()), mock.patch(
            "agent.web.desktop.MultiAgentSystem", _FakeMAS
        ), mock.patch("agent.web.desktop.threading.Thread", _ImmediateThread):
            app = DesktopApp(cfg)
            app.window = _FakeWindow()
            result = app.send_message("Run mission")

        self.assertEqual(result["status"], "started")
        self.assertIn("mission_id", result)
        self.assertTrue(result["mission_id"])  # non-empty UUID

        payloads = []
        for call in app.window.calls:
            prefix = "handleEvent("
            suffix = ")"
            if call.startswith(prefix) and call.endswith(suffix):
                payloads.append(json.loads(call[len(prefix):-len(suffix)]))
        event_types = [payload["type"] for payload in payloads]
        self.assertIn("info", event_types)
        self.assertIn("final", event_types)

    def test_send_message_persists_mission_to_store(self):
        cfg = self._load_config()

        with mock.patch("agent.web.desktop.build_agent", return_value=_FakeAgent()), mock.patch(
            "agent.web.desktop.MultiAgentSystem", _FakeMAS
        ), mock.patch("agent.web.desktop.threading.Thread", _ImmediateThread):
            app = DesktopApp(cfg)
            app.window = _FakeWindow()
            result = app.send_message("Persistent mission")

        mission_id = result["mission_id"]
        mission = app._store.get_mission(mission_id)
        self.assertIsNotNone(mission)
        self.assertEqual(mission["prompt"], "Persistent mission")
        self.assertEqual(mission["status"], "completed")
        self.assertEqual(mission["result"], "Mission finished.")
        self.assertGreater(len(mission["events"]), 0)

    def test_same_team_signature_reuses_multi_agent_instance(self):
        cfg = self._load_config()
        _FakeMAS.create_count = 0

        with mock.patch("agent.web.desktop.build_agent", return_value=_FakeAgent()), mock.patch(
            "agent.web.desktop.MultiAgentSystem", _FakeMAS
        ), mock.patch("agent.web.desktop.threading.Thread", _ImmediateThread):
            app = DesktopApp(cfg)
            app.window = _FakeWindow()
            app.send_message("Run mission", {"role": "Lead"}, [{"role": "Dev"}])
            app.send_message("Run mission again", {"role": "Lead"}, [{"role": "Dev"}])

        self.assertEqual(_FakeMAS.create_count, 1)
