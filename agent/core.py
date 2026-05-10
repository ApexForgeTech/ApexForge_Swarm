import json
import logging
import threading
from typing import Any, Dict, Generator, List, Optional

from .config import Config
from .errors import ApexError
from .events import done_event, error_event, interrupted_event, text_event, thought_event, tool_call_event, tool_result_event
from .llm_backend import LLMToolCall, create_llm_backend, get_backend_capabilities
from .logging_utils import log_event
from .memory import MemorySystem
from .request_router import RequestRouter
from .system_prompt import build_system_prompt
from .tool_executor import ToolExecutor
from .tools.base import BaseTool

logger = logging.getLogger("agent")
logger.addHandler(logging.NullHandler())

_COMPRESS_AT = 0.80


class Agent:
    def __init__(self, config: Config, memory: MemorySystem = None):
        self.config = config
        self.memory = memory or MemorySystem(config.skills_path, config.memory_path)
        self.tools: Dict[str, BaseTool] = {}
        self.tool_schemas: List[Dict[str, Any]] = []
        self.messages: List[Dict[str, Any]] = []
        self.pending_shell_command: Optional[str] = None
        self.llm = create_llm_backend(config)
        self.router = RequestRouter(config, self.memory)
        self.tool_executor = ToolExecutor(self.tools, logger)
        self._build_system_prompt()

    def _build_system_prompt(self):
        system = build_system_prompt(self.config, self.memory, self.tools)
        if self.messages:
            self.messages[0] = {"role": "system", "content": system}
        else:
            self.messages = [{"role": "system", "content": system}]

    def reload_memory(self):
        self._build_system_prompt()

    def load_messages(self, messages: List[Dict[str, Any]]):
        if not messages:
            return
        self.messages = [self.messages[0]] + [m for m in messages if m.get("role") != "system"]

    def register_tool(self, tool: BaseTool):
        self.tools[tool.name] = tool
        self.tool_schemas.append(tool.to_ollama_schema())
        self._build_system_prompt()

    def _run_direct_tool(
        self,
        user_message: str,
        tool_name: str,
        args: Dict[str, Any],
    ) -> Generator[Dict[str, Any], None, None]:
        self.messages.append({"role": "user", "content": user_message})
        self.pending_shell_command = None
        yield tool_call_event(tool_name, args, primary=True)
        result = self._call_tool(tool_name, args)
        yield tool_result_event(tool_name, result, primary=True)
        self.messages.append({"role": "assistant", "content": result})
        yield text_event(result)
        yield done_event()

    def _call_tool(self, name: str, args: Dict[str, Any]) -> str:
        return self.tool_executor.call_tool(name, args)

    def _execute_tool_with_fallback(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        return self.tool_executor.execute_with_fallback(name, args)

    def _token_estimate(self) -> int:
        total = 0
        for m in self.messages:
            content = str(m.get("content") or "")
            if content:
                non_ascii = sum(1 for c in content if ord(c) > 127)
                ascii_chars = len(content) - non_ascii
                # ASCII ~4 chars/token, Unicode (CJK/Cyrillic/etc.) ~2 chars/token
                total += ascii_chars // 4 + non_ascii // 2
            if m.get("tool_calls"):
                total += len(json.dumps(m["tool_calls"])) // 3
        return total

    def _maybe_compress(self):
        limit = self.config.ollama.num_ctx
        if self._token_estimate() < limit * _COMPRESS_AT:
            return
        if len(self.messages) <= 6:
            return
        system = self.messages[0]
        old = self.messages[1:-4]
        recent = self.messages[-4:]
        text = "\n".join(
            f"{m['role'].upper()}: {str(m.get('content', ''))[:400]}"
            for m in old if m.get("content")
        )
        try:
            summary = self.llm.chat_once(
                [
                    system,
                    {"role": "user", "content": f"Summarize this conversation history in bullet points:\n\n{text}"},
                ]
            )
            self.messages = [system, {"role": "assistant", "content": f"[Earlier summary]\n{summary}"}] + recent
        except Exception:
            self.messages = [system] + self.messages[-6:]

    def chat(
        self,
        user_message: str,
        images: Optional[List[str]] = None,
        interrupt: Optional[threading.Event] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        log_event(
            logger,
            logging.INFO,
            "agent_chat_started",
            provider=self.config.agent.provider,
            model=self.config.ollama.model,
            has_images=bool(images),
            message_preview=user_message,
        )
        self._maybe_compress()

        msg = {"role": "user", "content": self.router.prepare_user_message(user_message, images=images)}
        if images:
            msg["images"] = images

        direct_tool = self.router.route_simple_request(user_message, self.pending_shell_command)
        if direct_tool and not images:
            yield from self._run_direct_tool(user_message, direct_tool["name"], direct_tool["args"])
            return

        if (
            isinstance(user_message, str)
            and user_message.strip().startswith("!")
            and getattr(self.config, "autonomy", None) and getattr(self.config.autonomy, "enabled", False)
        ):
            command = user_message.strip()[1:].strip()
            if command:
                result = self._call_tool("auto_shell", {"command": command})
                yield tool_call_event("auto_shell", {"command": command}, primary=True)
                yield tool_result_event("auto_shell", result, primary=True)
                yield text_event(result)
                yield done_event()
                return

        self.messages.append(msg)

        for _ in range(self.config.agent.max_iterations):
            full_content = ""
            tool_calls: List[LLMToolCall] = []

            try:
                stream = self.llm.chat_stream(
                    messages=self.messages,
                    tools=self.tool_schemas or None,
                )
                is_thinking = False
                for chunk in stream:
                    if interrupt and interrupt.is_set():
                        interrupt.clear()
                        if full_content:
                            self.messages.append({"role": "assistant", "content": full_content + " [interrupted]"})
                        yield interrupted_event(full_content)
                        return

                    if chunk.content:
                        content = chunk.content
                        full_content += content

                        if "<thought>" in content:
                            is_thinking = True
                            thought_part = content.split("<thought>")[-1]
                            if thought_part:
                                yield thought_event(thought_part)
                            continue

                        if "</thought>" in content:
                            is_thinking = False
                            pre_thought = content.split("</thought>")[0]
                            if pre_thought:
                                yield thought_event(pre_thought)
                            continue

                        if is_thinking:
                            yield thought_event(content)
                        else:
                            yield text_event(content)

                    if chunk.tool_calls:
                        tool_calls = chunk.tool_calls

            except ApexError as exc:
                log_event(
                    logger,
                    logging.ERROR,
                    "agent_apex_error",
                    code=exc.code,
                    provider=exc.provider,
                    recoverable=exc.recoverable,
                    error=exc.message,
                )
                yield error_event(str(exc), code=exc.code)
                break
            except Exception as exc:
                log_event(logger, logging.ERROR, "agent_unexpected_error", error=str(exc))
                yield error_event(str(exc))
                break

            assistant_msg: Dict[str, Any] = {"role": "assistant", "content": full_content}
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ]
            self.messages.append(assistant_msg)
            if not tool_calls:
                self.pending_shell_command = self.router.extract_shell_command(full_content)
                log_event(
                    logger,
                    logging.INFO,
                    "agent_chat_completed",
                    provider=self.config.agent.provider,
                    model=self.config.ollama.model,
                    tool_calls=0,
                    response_preview=full_content,
                )
                break

            self.pending_shell_command = None
            for tc in tool_calls:
                name = tc.function.name
                raw = tc.function.arguments
                args = raw if isinstance(raw, dict) else json.loads(raw or "{}")

                yield tool_call_event(name, args, primary=True)

                if interrupt and interrupt.is_set():
                    interrupt.clear()
                    yield interrupted_event("")
                    return

                execution = self._execute_tool_with_fallback(name, args)
                for attempt in execution["attempts"][1:]:
                    yield tool_call_event(attempt["name"], attempt["args"], primary=False)
                    yield tool_result_event(attempt["name"], attempt["result"], primary=False)
                result = execution["final_result"]
                yield tool_result_event(name, result, primary=True)
                self.messages.append({"role": "tool", "content": result, "name": name, "tool_call_id": tc.id})

        if self.messages and self.messages[-1].get("role") == "assistant":
            assistant_message = str(self.messages[-1].get("content", "") or "")
            tool_count = len(self.messages[-1].get("tool_calls", []) or [])
            log_event(
                logger,
                logging.INFO,
                "agent_turn_finished",
                provider=self.config.agent.provider,
                model=self.config.ollama.model,
                tool_calls=tool_count,
                pending_shell=bool(self.pending_shell_command),
                response_preview=assistant_message,
            )
        yield done_event()

    def clear(self):
        self._build_system_prompt()

    def set_model(self, model: str):
        provider = self.config.agent.provider
        if provider == "llama_cpp" and hasattr(self.llm, "resolve_model_path"):
            resolved = self.llm.resolve_model_path(model)
            if resolved:
                self.config.llama_cpp.model_path = resolved
        if provider == "openai_compat":
            self.config.openai_compat.model = model
        self.config.ollama.model = model

    def set_provider(self, provider: str):
        self.config.agent.provider = provider
        self.llm = create_llm_backend(self.config)

    def available_models(self) -> List[str]:
        return self.llm.list_models()

    def backend_capabilities(self) -> Dict[str, Any]:
        return get_backend_capabilities(self.config).as_dict()

    def token_estimate(self) -> int:
        return self._token_estimate()

    def message_count(self) -> int:
        return max(0, len(self.messages) - 1)

    def export_markdown(self) -> str:
        lines = ["# ApexForge Swarm — Conversation Export\n"]
        for message in self.messages:
            role = message.get("role", "")
            content = message.get("content", "")
            if role == "system":
                continue
            if role == "user":
                lines.append(f"**You:** {content}\n")
            elif role == "assistant":
                lines.append(f"**Agent:** {content}\n")
            elif role == "tool":
                lines.append(f"> `{message.get('name', 'tool')}` → {str(content)[:300]}\n")
        return "\n".join(lines)
