import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from agent.config import Config
from agent.multi_agent import MultiAgentSystem


class _FakeAgent:
    def __init__(self, name: str):
        self.name = name
        self.messages = [{"role": "system", "content": "fake"}]

    def set_model(self, _model: str):
        return None


class MultiAgentFlowTests(unittest.TestCase):
    def _load_config(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        config_path = Path(tmpdir.name) / "config.yaml"
        config_path.write_text("{}", encoding="utf-8")
        return Config.load(config_path)

    def test_chat_emits_assignment_report_and_final_events(self):
        cfg = self._load_config()
        cfg.agent.provider = "ollama"

        def fake_create_agent(self, name, role, model=None):
            return _FakeAgent(name)

        def fake_collect(self, agent, prompt, stream_text, interrupt=None):
            if agent.name == "Supervisor" and "Create a concrete plan" in prompt:
                return (
                    '{"mission":"Audit the repo","success_criteria":["Find issues","Summarize results"],'
                    '"assignments":[{"worker":"Worker_1","task":"Inspect engine"},{"worker":"Worker_2","task":"Verify behavior"}]}',
                    [],
                    False,
                )
            if agent.name == "Worker_1":
                return (
                    "Engine inspection finished with concrete notes.",
                    [{"type": "agent_chat", "agent": agent.name, "data": "Inspecting engine."}],
                    False,
                )
            if agent.name == "Worker_2":
                return (
                    "Verification finished with concrete notes.",
                    [{"type": "agent_chat", "agent": agent.name, "data": "Running verification."}],
                    False,
                )
            if agent.name == "Supervisor" and "reviewing worker outputs" in prompt:
                return (
                    '{"status":"complete","summary":"The mission is complete.","final_answer":"Combined final answer.","feedback":"","assignments":[]}',
                    [],
                    False,
                )
            return ("", [], False)

        with mock.patch.object(MultiAgentSystem, "_create_agent", fake_create_agent), mock.patch.object(
            MultiAgentSystem, "_collect_agent_run", fake_collect
        ):
            mas = MultiAgentSystem(
                cfg,
                {"role": "Lead"},
                [{"role": "Developer"}, {"role": "Tester"}],
            )
            events = list(mas.chat("Analyze the repository"))

        event_types = [event["type"] for event in events]
        self.assertIn("assignment", event_types)
        self.assertIn("report", event_types)
        self.assertIn("review", event_types)
        self.assertIn("final", event_types)
        self.assertEqual(events[-1]["type"], "done")
        final_event = next(event for event in events if event["type"] == "final")
        self.assertEqual(final_event["data"], "Combined final answer.")

    def test_llama_cpp_mixed_models_emit_backend_warnings(self):
        cfg = self._load_config()
        cfg.agent.provider = "llama_cpp"

        with mock.patch.object(MultiAgentSystem, "_create_agent", lambda self, name, role, model=None: _FakeAgent(name)):
            mas = MultiAgentSystem(
                cfg,
                {"role": "Lead", "model": "supervisor.gguf"},
                [{"role": "Developer", "model": "worker.gguf"}, {"role": "Tester", "model": "qa.gguf"}],
            )

        self.assertGreaterEqual(len(mas.backend_warnings), 2)
        self.assertTrue(any("Normalized all agents" in warning for warning in mas.backend_warnings))

    def test_chat_emits_interrupted_when_interrupt_is_pre_set(self):
        cfg = self._load_config()
        cfg.agent.provider = "ollama"
        stop = threading.Event()
        stop.set()

        with mock.patch.object(MultiAgentSystem, "_create_agent", lambda self, name, role, model=None: _FakeAgent(name)):
            mas = MultiAgentSystem(
                cfg,
                {"role": "Lead"},
                [{"role": "Developer"}],
            )
            events = list(mas.chat("Analyze the repository", interrupt=stop))

        event_types = [event["type"] for event in events]
        self.assertIn("interrupted", event_types)
        self.assertEqual(events[-1]["type"], "done")
