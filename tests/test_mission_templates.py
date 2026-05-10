"""Tests for mission_templates.py and MessageBus."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from agent.mission_templates import (
    TEMPLATES,
    apply_template,
    describe_templates,
    get_template,
    list_templates,
)
from agent.multi_agent import MessageBus, MultiAgentSystem


# ── Templates ─────────────────────────────────────────────────────────────────

class TemplateRegistryTests(unittest.TestCase):
    def test_all_expected_templates_present(self):
        names = set(list_templates())
        expected = {"code_review", "research", "repo_audit", "document_processing",
                    "bug_investigation", "feature_planning", "data_analysis"}
        self.assertEqual(names, expected)

    def test_each_template_has_required_keys(self):
        for name, tmpl in TEMPLATES.items():
            with self.subTest(template=name):
                self.assertIn("supervisor", tmpl)
                self.assertIn("workers", tmpl)
                self.assertIn("hint", tmpl)
                self.assertIn("description", tmpl)
                self.assertIsInstance(tmpl["workers"], list)
                self.assertGreater(len(tmpl["workers"]), 0)

    def test_each_worker_has_role(self):
        for name, tmpl in TEMPLATES.items():
            for worker in tmpl["workers"]:
                with self.subTest(template=name, worker=worker):
                    self.assertIn("role", worker)
                    self.assertTrue(worker["role"].strip())

    def test_get_template_returns_dict(self):
        tmpl = get_template("code_review")
        self.assertIsNotNone(tmpl)
        self.assertIsInstance(tmpl, dict)

    def test_get_template_returns_none_for_unknown(self):
        self.assertIsNone(get_template("nonexistent_template_xyz"))

    def test_describe_templates_returns_name_and_description(self):
        items = describe_templates()
        self.assertEqual(len(items), len(TEMPLATES))
        for item in items:
            self.assertIn("name", item)
            self.assertIn("description", item)
            self.assertTrue(item["description"])

    def test_apply_template_returns_supervisor_and_workers(self):
        result = apply_template("research")
        self.assertIsNotNone(result)
        supervisor, workers = result
        self.assertIn("role", supervisor)
        self.assertIsInstance(workers, list)
        self.assertGreater(len(workers), 0)

    def test_apply_template_supervisor_override(self):
        result = apply_template("code_review", supervisor_override={"role": "Custom Lead"})
        supervisor, _ = result
        self.assertEqual(supervisor["role"], "Custom Lead")

    def test_apply_template_workers_override(self):
        custom_workers = [{"role": "Specialist A"}, {"role": "Specialist B"}]
        _, workers = apply_template("repo_audit", workers_override=custom_workers)
        self.assertEqual(workers, custom_workers)

    def test_apply_template_returns_copies_not_references(self):
        result1 = apply_template("bug_investigation")
        result2 = apply_template("bug_investigation")
        sup1, wkr1 = result1
        sup2, wkr2 = result2
        sup1["role"] = "mutated"
        self.assertNotEqual(sup2["role"], "mutated")

    def test_apply_template_unknown_returns_none(self):
        self.assertIsNone(apply_template("totally_unknown"))


# ── MultiAgentSystem.from_template ────────────────────────────────────────────

class _FakeAgent:
    def __init__(self, name: str):
        self.name = name
        self.messages = [{"role": "system", "content": "fake"}]

    def set_model(self, _model: str):
        return None


class FromTemplateTests(unittest.TestCase):
    def _config(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        from agent.config import Config
        cfg_path = Path(tmpdir.name) / "config.yaml"
        cfg_path.write_text("{}", encoding="utf-8")
        return Config.load(cfg_path)

    def test_from_template_builds_correct_worker_count(self):
        cfg = self._config()
        with mock.patch.object(MultiAgentSystem, "_create_agent", lambda self, name, role, model=None, host=None: _FakeAgent(name)):
            mas = MultiAgentSystem.from_template(cfg, "code_review")
        self.assertEqual(len(mas.workers), len(TEMPLATES["code_review"]["workers"]))

    def test_from_template_stores_template_name(self):
        cfg = self._config()
        with mock.patch.object(MultiAgentSystem, "_create_agent", lambda self, name, role, model=None, host=None: _FakeAgent(name)):
            mas = MultiAgentSystem.from_template(cfg, "research")
        self.assertEqual(mas.template_name, "research")

    def test_from_template_stores_hint(self):
        cfg = self._config()
        with mock.patch.object(MultiAgentSystem, "_create_agent", lambda self, name, role, model=None, host=None: _FakeAgent(name)):
            mas = MultiAgentSystem.from_template(cfg, "data_analysis")
        self.assertTrue(mas.template_hint)
        self.assertIn("tool", mas.template_hint.lower())

    def test_from_template_raises_for_unknown(self):
        cfg = self._config()
        with self.assertRaises(ValueError):
            MultiAgentSystem.from_template(cfg, "totally_bogus_template")

    def test_from_template_supervisor_override(self):
        cfg = self._config()
        with mock.patch.object(MultiAgentSystem, "_create_agent", lambda self, name, role, model=None, host=None: _FakeAgent(name)):
            mas = MultiAgentSystem.from_template(cfg, "feature_planning", supervisor_override={"role": "My Lead"})
        self.assertEqual(mas.supervisor_role, "My Lead")

    def test_from_template_has_message_bus(self):
        cfg = self._config()
        with mock.patch.object(MultiAgentSystem, "_create_agent", lambda self, name, role, model=None, host=None: _FakeAgent(name)):
            mas = MultiAgentSystem.from_template(cfg, "repo_audit")
        self.assertIsInstance(mas.bus, MessageBus)


# ── MessageBus ────────────────────────────────────────────────────────────────

class MessageBusTests(unittest.TestCase):
    def test_send_and_receive(self):
        bus = MessageBus()
        bus.send("Alice", "Bob", "hello Bob")
        messages = bus.receive("Bob")
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["from"], "Alice")
        self.assertEqual(messages[0]["content"], "hello Bob")

    def test_receive_clears_mailbox(self):
        bus = MessageBus()
        bus.send("A", "B", "msg1")
        bus.receive("B")
        self.assertEqual(bus.receive("B"), [])

    def test_peek_does_not_consume(self):
        bus = MessageBus()
        bus.send("A", "B", "peek test")
        bus.peek("B")
        messages = bus.receive("B")
        self.assertEqual(len(messages), 1)

    def test_multiple_senders_to_same_recipient(self):
        bus = MessageBus()
        bus.send("W1", "Supervisor", "report from W1")
        bus.send("W2", "Supervisor", "report from W2")
        messages = bus.receive("Supervisor")
        self.assertEqual(len(messages), 2)
        senders = {m["from"] for m in messages}
        self.assertIn("W1", senders)
        self.assertIn("W2", senders)

    def test_separate_mailboxes_for_different_recipients(self):
        bus = MessageBus()
        bus.send("A", "B", "for B")
        bus.send("A", "C", "for C")
        self.assertEqual(bus.receive("B")[0]["content"], "for B")
        self.assertEqual(bus.receive("C")[0]["content"], "for C")

    def test_receive_empty_mailbox(self):
        bus = MessageBus()
        self.assertEqual(bus.receive("nobody"), [])

    def test_pending_count(self):
        bus = MessageBus()
        bus.send("A", "B", "m1")
        bus.send("A", "B", "m2")
        self.assertEqual(bus.pending_count("B"), 2)
        self.assertEqual(bus.pending_count("C"), 0)

    def test_clear_specific_recipient(self):
        bus = MessageBus()
        bus.send("A", "B", "m1")
        bus.send("A", "C", "m2")
        bus.clear("B")
        self.assertEqual(bus.receive("B"), [])
        self.assertEqual(len(bus.receive("C")), 1)

    def test_clear_all(self):
        bus = MessageBus()
        bus.send("A", "B", "m1")
        bus.send("A", "C", "m2")
        bus.clear()
        self.assertEqual(bus.receive("B"), [])
        self.assertEqual(bus.receive("C"), [])

    def test_message_carries_timestamp(self):
        bus = MessageBus()
        bus.send("A", "B", "ts test")
        msg = bus.receive("B")[0]
        self.assertIn("ts", msg)
        self.assertTrue(msg["ts"])

    def test_message_carries_meta(self):
        bus = MessageBus()
        bus.send("A", "B", "meta test", meta={"priority": "high"})
        msg = bus.receive("B")[0]
        self.assertEqual(msg["meta"]["priority"], "high")

    def test_thread_safety_concurrent_sends(self):
        bus = MessageBus()
        errors = []

        def sender(worker_id: int):
            try:
                for i in range(50):
                    bus.send(f"W{worker_id}", "Supervisor", f"msg{i}")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=sender, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        messages = bus.receive("Supervisor")
        self.assertEqual(len(messages), 250)
