import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent.config import Config
from agent.core import Agent
from agent.llm_backend import LLMChunk, LLMToolCall, LLMToolCallFunction
from agent.request_router import RequestRouter
from agent.tools.file_tools import WriteFileTool


class _FakeMemory:
    def build_context(self):
        return ""

    def list_skills(self):
        return []


class _EnforcingFakeBackend:
    def chat_stream(self, messages, tools=None):
        last = messages[-1]["content"]
        if "Execution reminder:" in last:
            yield LLMChunk(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call_1",
                        function=LLMToolCallFunction(
                            name="write_file",
                            arguments={"path": self.path, "content": "print('hi')\n"},
                        ),
                    )
                ],
            )
            return
        if messages[-1].get("role") == "tool":
            yield LLMChunk(content="Done. The file is now written.")
            return
        yield LLMChunk(content="I created the file successfully.")

    def list_models(self):
        return []

    def capabilities(self):
        class _Caps:
            def as_dict(self_inner):
                return {}
        return _Caps()


class AgentExecutionSafetyTests(unittest.TestCase):
    def test_router_inherits_execution_context_for_short_followups(self):
        cfg = Config()
        router = RequestRouter(cfg, _FakeMemory())
        self.assertTrue(router.should_inherit_execution_context("yap"))
        self.assertTrue(router.should_inherit_execution_context("random yap"))
        self.assertTrue(router.should_inherit_execution_context("olusturulmadi"))

    def test_agent_retries_with_tool_instead_of_accepting_fake_file_claim(self):
        cfg = Config()
        cfg.agent.max_iterations = 4

        with tempfile.TemporaryDirectory() as tmpdir:
            target = str(Path(tmpdir) / "main.py")
            backend = _EnforcingFakeBackend()
            backend.path = target

            with mock.patch("agent.core.create_llm_backend", return_value=backend):
                agent = Agent(cfg, memory=_FakeMemory())
            agent.register_tool(WriteFileTool())

            events = list(agent.chat(f"create a python file at {target}"))

            text_parts = [ev["data"] for ev in events if ev["type"] == "text"]
            tool_calls = [ev for ev in events if ev["type"] == "tool_call"]

            self.assertTrue(Path(target).exists())
            self.assertTrue(any(call["data"]["name"] == "write_file" for call in tool_calls))
            self.assertFalse(any("I created the file successfully." in part for part in text_parts))
            self.assertTrue(any("Done. The file is now written." in part for part in text_parts))
